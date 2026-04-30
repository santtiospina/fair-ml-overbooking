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

        # Snapshot of originally-overbooked slots, captured before simulation runs.
        self.original_overbooked_slots = {}
        
        # CRC: counts patients who were stackers at an originally-overbooked slot
        # where BOTH anchor and stacker attended (a real conflict at the original slot).
        self.crc_protected = 0
        self.crc_non_protected = 0

        # CR: counts patients who were displaced from their originally-booked slot
        # (waiting_time > 0 for any reason — direct push or cascade victim).
        # Each patient counted at most once (deduplicated by id).
        self.cr_protected = 0
        self.cr_non_protected = 0

        # Internal: track which patients have already been counted in CR
        # to enforce "at most once per patient."
        self._cr_counted_ids = set()


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
 
    def _snapshot_original_overbookings(self):
        """
        Captures the originally-overbooked slots as constructed by the rule,
        BEFORE simulation() mutates the schedule via cascade pushes.
 
        Creates a new list of occupant IDs per slot (not a reference to the
        slot list itself), so the snapshot is safe from in-place mutations.
 
        Stored in self.original_overbooked_slots as:
            {(server_idx, dia_idx, slot_idx): {
                "anchor":   pid at index 0,
                "stackers": [pid at index 1, ...]
            }}
        """
        self.original_overbooked_slots = {}
        for server_idx, server in enumerate(self.appointments):
            for dia_idx, dia in enumerate(server):
                for slot_idx, slot in enumerate(dia):
                    occupants = [pid for pid in slot if pid is not None]
                    if len(occupants) >= 2:
                        self.original_overbooked_slots[(server_idx, dia_idx, slot_idx)] = {
                            "anchor": occupants[0],
                            "stackers": occupants[1:],
                        }

    def _compute_conflict_metrics(self):
        """
        Post-simulation pass that computes CRC and CR from the snapshot and
        the per-patient waiting times recorded during simulation().
 
        Must be called AFTER simulation() completes — it relies on
        patient.waiting_time being set by _record_attendance().
 
        CRC
        ---
        For each originally-overbooked slot: if the anchor attended AND at
        least one stacker also attended, count each attending stacker once
        for their group. The anchor is never counted. Cascade-victim slots
        (not in the snapshot) are never counted.
 
        CR
        ---
        Walk all patients. Any attendee whose waiting_time > 0 was displaced
        from their originally-booked slot — count them once for their group.
        The deduplication set _cr_counted_ids prevents double-counting for
        patients who pass through multiple cascade steps.
        """
        # ============================================================
        # #                           CRC                            #
        # #                      Walk snapshot                       #
        # #      Check attendance at original-overbooked slots       #
        # ============================================================

        crc_counted_ids = set()
        for (server_idx, dia_idx, slot_idx), members in self.original_overbooked_slots.items():
            anchor_id = members["anchor"]
            stackers = members["stackers"]

            anchor_attended = self.patients_list[anchor_id].attendance
            if not anchor_attended:
                # No real conflict at the originally-overbooked slot — anchor absent.
                continue

            for stacker_id in stackers:
                stacker_attended = self.patients_list[stacker_id].attendance
                if not stacker_attended:
                    continue
                # Real original conflict: both anchor and this stacker attended.
                if stacker_id in crc_counted_ids:
                    continue  # already counted (defensive; rule shouldn't double-stack)
                crc_counted_ids.add(stacker_id)
                if self.patients_list[stacker_id].protected:
                    self.crc_protected += 1
                else:
                    self.crc_non_protected += 1

        # ============================================================
        # #                            CR                            #
        # #                  Walk the patients list                  #
        # #         Count any attendee with waiting_time > 0         #
        # ============================================================

        for patient in self.patients_list:
            if not patient.attendance:
                continue
            if not patient.assigned:
                continue
            if patient.waiting_time <= 0:
                continue
            if patient.id in self._cr_counted_ids:
                continue
            self._cr_counted_ids.add(patient.id)
            if patient.protected:
                self.cr_protected += 1
            else:
                self.cr_non_protected += 1

    def simulation(self):
        # Snapshot the schedule BEFORE any cascade mutations.
        # Required for CRC to identify originally-overbooked slots.
        self._snapshot_original_overbookings()

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
                                # Every patient in ids bears the waiting-time cost.
                                # NOTE: conflict_slots_* increments removed — CRC/CR
                                # are computed in the post-pass _compute_conflict_metrics().
                                self.over_time[server_idx] += self.slot_time * (len(ids) - 1)
                                for i, pid in enumerate(ids):
                                    self._record_attendance(pid, slot_idx + i)
 
                            else:
                              # Cascade: ids[0] served at this slot. ids[1:] prepended
                                # to the next slot's list and processed there.
                                # Because overflow is prepended (overflow + next_slot_existing),
                                # the pushed patient becomes ids[0] of the next slot and is
                                # served there without being re-bumped — unless the next slot
                                # also has two attendees, which is a separate independent event.
                                # NOTE: conflict_slots_* increment removed — see above.
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
        # Post-pass: compute CRC and CR from snapshot + recorded waiting times.
        # Must run after the simulation loop so all waiting_time values are set.
        self._compute_conflict_metrics()
 
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

            # CRC: cause-attributed conflict counts (stackers at original-conflict slots)
            "crc_protected": self.crc_protected,
            "crc_non_protected": self.crc_non_protected,
            "crc_rate_protected": (
                self.crc_protected / self.protected_assistance
                if self.protected_assistance > 0 else 0
            ),
            "crc_rate_non_protected": (
                self.crc_non_protected / self.non_protected_assistance
                if self.non_protected_assistance > 0 else 0
            ),

            # CR: any displacement (stacker losing original conflict OR cascade victim)
            "cr_protected": self.cr_protected,
            "cr_non_protected": self.cr_non_protected,
            "cr_rate_protected": (
                self.cr_protected / self.protected_assistance
                if self.protected_assistance > 0 else 0
            ),
            "cr_rate_non_protected": (
                self.cr_non_protected / self.non_protected_assistance
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
