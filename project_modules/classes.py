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
    def __init__(self, patients_data, appointments, slot_time):
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

                    # ── Empty or all-None slot: idle ─────────────────────────
                    if slot.count(None) == len(slot):
                        self.idle_time_server[server_idx] += self.slot_time
                        continue

                    n_real = self.not_null(slot)

                    # ── Exactly one patient scheduled ────────────────────────
                    if n_real == 1:
                        patient_id = next(pid for pid in slot if pid is not None)

                        if not self.patients_list[patient_id].attendance:
                            self.appointments[server_idx][dia_idx][slot_idx] = []
                            self.idle_time_server[server_idx] += self.slot_time
                            self.no_shows += 1
                        else:
                            self._record_attendance(patient_id, slot_idx)

                    # ── More than one patient scheduled (overbooking) ────────
                    else:
                        ids = []
                        for pid in slot:
                            if pid is None:
                                continue
                            if self.patients_list[pid].attendance:
                                ids.append(pid)
                            else:
                                self.no_shows += 1

                        self.appointments[server_idx][dia_idx][slot_idx] = ids if ids else []

                        if len(ids) == 0:
                            self.idle_time_server[server_idx] += self.slot_time

                        elif len(ids) == 1:
                            # Only one of the overbooked patients showed — no conflict
                            self._record_attendance(ids[0], slot_idx)

                        else:
                            is_last_slot = (
                                slot_idx == len(self.appointments[server_idx][dia_idx]) - 1
                            )

                            if is_last_slot:
                                # Overtime: serve all sequentially past end-of-day
                                self.over_time[server_idx] += self.slot_time * (len(ids) - 1)
                                for i, pid in enumerate(ids):
                                    self._record_attendance(pid, slot_idx + i)

                            else:
                                # Cascade: serve ids[0] now, push ids[1:] to next slot
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
        }
        return measures
