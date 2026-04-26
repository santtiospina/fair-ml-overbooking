# project_modules/classes.py
from project_modules.project_imports import *

class Patient:
    def __init__(self, id, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

        self.id = id
        self.proba = 0
        self.protected = False
        self.attendance = True
        self.assigned = False
        self.day_of_call = 0
        self.num_slot = -1
        self.waiting_time = 0
        self.overbooked = False           # true conflict (double-booked)
        self.overbooked_target = False    # eligibility flag (proba > threshold)

        if self.regime_subsidized == 1:
            self.protected = True

    def predict_proba(self, model):
        patient_data = pd.DataFrame([self.__dict__])
        patient_data = patient_data.drop(columns=[
            'id', 'proba', 'protected', 'attendance',
            'assigned', 'day_of_call', 'num_slot',
            'overbooked', 'overbooked_target', 'waiting_time'
        ])
        prediction = model.predict_proba(patient_data)[:, -1][0]
        self.proba = prediction
        return prediction

class Clinic:
    def __init__(
        self,
        patients_data,
        appointments,
        slot_time,
    ):
        """
        Parameters
        ----------
        patients_data : list of Patient
        appointments  : nested list produced by the scheduling rule.
                        Service order within each slot is determined
                        entirely by the rule — the simulation preserves
                        it without reordering.
        slot_time     : int, slot duration in minutes.
 
        Service-order contract
        ----------------------
        The simulation serves ids[0] at the booked slot and pushes
        ids[1:] forward. Rules are responsible for placing patients in
        the correct order when constructing slots:
            index 0 → patient to be served first (non-flagged / predicted show)
            index 1 → patient who bears the WT cost (flagged / predicted no-show)
 
        For rule_simple_pairing this is guaranteed by construction:
        Step 2 places the non-flagged patient at current[0], then
        Step 1 appends the flagged patient via current.append(), making
        them current[1]. No sorting is applied here so cascade conflicts
        do not compound waiting time beyond the original conflict slot.
        """
        self.appointments = appointments
        self.patients_list = patients_data
        self.slot_time = slot_time
 
        self.over_time = np.zeros(len(self.appointments))
        self.no_shows = 0
        self.idle_time_server = np.zeros(len(self.appointments))
 
        self.protected_assistance = 0
        self.non_protected_assistance = 0
        self.cwt_protected = 0
        self.cwt_non_protected = 0
 
        # Accumulated during simulation() via _record_attendance()
        self.protected_overbooked_patients = 0
        self.non_protected_overbooked_patients = 0
        self.protected_overbooked_waiting_time = 0
        self.non_protected_overbooked_waiting_time = 0
        self.total_attended_patients = 0
 
        # Conflict-slot diagnostics: counts patients in slots where ≥2 actually attended
        self.conflict_slots_protected = 0
        self.conflict_slots_non_protected = 0
 
    def compute_waiting_time(self, slot, patient_id):
        """
        Waiting time = slots delayed past original booking * slot_time (minutes).
        Only captures intra-schedule slot delay; cross-day waits are not modelled.
        """
        return max(0, (slot - self.patients_list[patient_id].num_slot) * self.slot_time)
 
    def _record_attendance(self, patient_id, actual_slot_idx):
        """
        Called exactly once per attending patient. Records waiting time,
        assistance counts, and overbooked-patient metrics.
        """
        wt = self.compute_waiting_time(actual_slot_idx, patient_id)
        patient = self.patients_list[patient_id]
        patient.waiting_time = wt
        self.total_attended_patients += 1
 
        if patient.protected:
            self.cwt_protected += wt
            self.protected_assistance += 1
        else:
            self.cwt_non_protected += wt
            self.non_protected_assistance += 1
 
        if patient.overbooked and patient.assigned:
            if patient.protected:
                self.protected_overbooked_patients += 1
                self.protected_overbooked_waiting_time += wt
            else:
                self.non_protected_overbooked_patients += 1
                self.non_protected_overbooked_waiting_time += wt
 
    def simulation(self):
        for server_idx, server in enumerate(self.appointments):
            for dia_idx, dia in enumerate(server):
                for slot_idx, slot in enumerate(dia):
 
                    # -- Empty or all-None slot: idle -------------------------
                    if slot.count(None) == len(slot):
                        self.idle_time_server[server_idx] += self.slot_time
                        continue
 
                    n_real = self.not_null(slot)
 
                    # -- Exactly one patient scheduled ------------------------
                    if n_real == 1:
                        patient_id = next(pid for pid in slot if pid is not None)
 
                        if not self.patients_list[patient_id].attendance:
                            self.appointments[server_idx][dia_idx][slot_idx] = []
                            self.idle_time_server[server_idx] += self.slot_time
                            self.no_shows += 1
                        else:
                            self._record_attendance(patient_id, slot_idx)
 
                    # -- More than one patient scheduled (overbooking) --------
                    else:
                        ids = []
                        for pid in slot:
                            if pid is None:
                                continue
                            if self.patients_list[pid].attendance:
                                ids.append(pid)
                            else:
                                self.no_shows += 1
 
                        # Service order is preserved exactly as the rule constructed
                        # the slot. No reordering is applied here.
                        # For rule_simple_pairing:
                        #   ids[0] = non-flagged patient (predicted show) → served at slot, WT=0
                        #   ids[1] = flagged patient (predicted no-show who attended) → pushed forward, WT=slot_time
                        # In downstream cascade slots, the pushed patient is at ids[0]
                        # of the next slot (prepended via overflow + next_slot_existing),
                        # so they are served there without being re-bumped again.
                        self.appointments[server_idx][dia_idx][slot_idx] = ids if ids else []
 
                        if len(ids) == 0:
                            self.idle_time_server[server_idx] += self.slot_time
 
                        elif len(ids) == 1:
                            # Only one patient showed — no conflict, no push.
                            self._record_attendance(ids[0], slot_idx)
 
                        else:
                            is_last_slot = (
                                slot_idx == len(self.appointments[server_idx][dia_idx]) - 1
                            )
 
                            if is_last_slot:
                                # Overtime: all patients attend simultaneously.
                                # Every patient in ids bears the conflict cost.
                                for pid in ids:
                                    if self.patients_list[pid].protected:
                                        self.conflict_slots_protected += 1
                                    else:
                                        self.conflict_slots_non_protected += 1
 
                                self.over_time[server_idx] += self.slot_time * (len(ids) - 1)
                                for i, pid in enumerate(ids):
                                    self._record_attendance(pid, slot_idx + i)
 
                            else:
                                # Cascade: ids[0] served at this slot (WT = accumulated delay
                                # from any prior pushes, 0 if this is the original booking).
                                # ids[1:] prepended to the next slot's list and processed there.
                                # Because overflow is prepended (overflow + next_slot_existing),
                                # the pushed patient becomes ids[0] of the next slot and is
                                # served there — they are not re-bumped a second time unless
                                # the next slot also has two attendees.
                                pid0 = ids[0]
                                if self.patients_list[pid0].protected:
                                    self.conflict_slots_protected += 1
                                else:
                                    self.conflict_slots_non_protected += 1
 
                                self._record_attendance(ids[0], slot_idx)
                                self.appointments[server_idx][dia_idx][slot_idx] = [ids[0]]
 
                                overflow = ids[1:]
                                next_slot_existing = [
                                    pid for pid in
                                    self.appointments[server_idx][dia_idx][slot_idx + 1]
                                    if pid is not None
                                ]
                                self.appointments[server_idx][dia_idx][slot_idx + 1] = (
                                    overflow + next_slot_existing
                                )
 
    def not_null(self, lista):
        return max(len(lista) - lista.count(None), 0)
 
    def get_measures(self):
        total_waiting_time = self.cwt_protected + self.cwt_non_protected
 
        measures = {
            "idle_time_server": self.idle_time_server.tolist(),
            "over_time": self.over_time.tolist(),
            "no_shows": self.no_shows,
            "clients_total_waiting_time protected class": max(0, self.cwt_protected),
            "clients_total_waiting_time non protected class": max(0, self.cwt_non_protected),
            "protected_assistance": self.protected_assistance,
            "non_protected_assistance": self.non_protected_assistance,
            "protected_overbooked_patients": self.protected_overbooked_patients,
            "non_protected_overbooked_patients": self.non_protected_overbooked_patients,
            "protected_overbooked_waiting_time": self.protected_overbooked_waiting_time,
            "non_protected_overbooked_waiting_time": self.non_protected_overbooked_waiting_time,
            "total_attended_patients": self.total_attended_patients,
            "total_waiting_time": total_waiting_time,
            "patient_waiting_time": (
                total_waiting_time / self.total_attended_patients
                if self.total_attended_patients > 0 else 0
            ),
            # Conflict-slot raw counts
            "conflict_slots_protected": self.conflict_slots_protected,
            "conflict_slots_non_protected": self.conflict_slots_non_protected,
            # Conflict-slot rates — normalized by attendance
            "conflict_rate_protected": (
                self.conflict_slots_protected / self.protected_assistance
                if self.protected_assistance > 0 else 0
            ),
            "conflict_rate_non_protected": (
                self.conflict_slots_non_protected / self.non_protected_assistance
                if self.non_protected_assistance > 0 else 0
            ),
            "protected_mean_wt": (
                self.cwt_protected / self.protected_assistance
                if self.protected_assistance > 0 else 0
            ),
            "non_protected_mean_wt": (
                self.cwt_non_protected / self.non_protected_assistance
                if self.non_protected_assistance > 0 else 0
            ),
        }
        return measures