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
        self.displaced_once = False       # True after first N-slot displacement
        self.pending_anchor = False  # True if placed alone via descending Step 1, waiting for anchor

        if self.regime_subsidized == 1:
            self.protected = True

    def predict_proba(self, model):
        patient_data = pd.DataFrame([self.__dict__])
        patient_data = patient_data.drop(columns=[
            'id', 'proba', 'protected', 'attendance',
            'assigned', 'day_of_call', 'num_slot',
            'overbooked', 'overbooked_target', 'waiting_time',
            'displaced_once', 'pending_anchor',
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
        displacement_offset: int = 1,
    ):
        """
        Parameters
        ----------
        patients_data : list of Patient
        appointments  : nested list produced by the scheduling rule.
        slot_time     : int, slot duration in minutes.
        displacement_offset : int, default 1.
            N — how many slots forward to push an originally-booked flagged
            stacker when a real conflict occurs at their booked slot.
 
        Service-order contract
        ----------------------
        At every slot t, the attending candidate pool is built from:
          1. All patients currently in the slot list (cascade arrivals from
             prior +1 pushes AND the slot's own anchor/stacker). Every
             patient in the slot list who attends is always a candidate —
             the N-slot rule governs where they go AFTER displacement, not
             whether they participate in the conflict at their own booking.
          2. Pending-buffer stackers — ONLY if pool from (1) is empty
             (slot would be idle). Among pending stackers, any are eligible
             regardless of N-fulfillment when the slot is idle. When the
             slot is not idle, pending stackers who have fulfilled their
             N-slot wait (slot_idx >= stacker.num_slot + N) are also served.
 
        Sort key: (num_slot, overbooked_target).
          Cascade patients (num_slot < slot_idx) before own patients.
          Among same num_slot: anchor (False=0) before stacker (True=1).
 
        Displacement policy
        -------------------
        displacement_offset = 1 (default):
            Standard cascade. Stacker prepended to slot+1 immediately.
 
        displacement_offset = N > 1:
            Models deferred-service rules without full mechanical complexity.
            When a stacker is displaced from their ORIGINALLY BOOKED slot
            for the first time (patient.displaced_once == False), they enter
            a per-day pending buffer. The buffer is checked at every
            subsequent slot:
              - If the slot would be idle: serve the earliest pending stacker
                regardless of N-fulfillment (idle intermediate slot rule).
              - If the slot is not idle but slot_idx >= stacker.num_slot + N:
                the stacker is eligible and included in the candidate pool.
              - End of day: all remaining pending stackers are flushed to
                overtime in num_slot order.
 
            All other displaced patients (anchors bumped by cascade arrivals,
            cascade patients bumped again, stackers already displaced once)
            use standard +1 cascade push.
 
            patient.displaced_once is set True after the first N-slot entry
            into the buffer, preventing double-application of the N penalty.
        """
        self.appointments = appointments
        self.patients_list = patients_data
        self.slot_time = slot_time
        self.displacement_offset = displacement_offset
 
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

        # CR-flagged: displacements (waiting_time > 0) restricted to flagged
        # patients. Numerator counts flagged attendees displaced; denominator
        # (cr_flagged_*_assigned) counts all flagged attendees in the group.
        self.cr_flagged_protected = 0
        self.cr_flagged_non_protected = 0

        # Waiting time accumulated by flagged attendees (proba > group threshold).
        # Sum of waiting_time across all flagged patients who attended,
        # regardless of slot position (anchor, stacker, or alone).
        self.cwt_flagged_protected = 0
        self.cwt_flagged_non_protected = 0

        # Waiting time accumulated by TRULY STACKED patients (overbooked == True).
        # Distinct from cwt_flagged_*, which uses overbooked_target. The truly-stacked
        # pool excludes flagged patients who fell through to fallback empty slots.
        self.cwt_stacked_protected = 0
        self.cwt_stacked_non_protected = 0

        # Displacement count restricted to truly-stacked patients.
        self.cr_stacked_protected = 0
        self.cr_stacked_non_protected = 0
        
        # Displacement diagnostics — track how the N-slot penalty is resolved.
        self.idle_rule_served = 0
        self.n_fulfilled_served = 0

        # Track each group's count of patients placed as flagged stackers by the rule (regardless of whether they attended)
        self.protected_overbooked_assigned = 0
        self.non_protected_overbooked_assigned = 0

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

        if patient.overbooked_target:
            if patient.protected:
                self.cwt_flagged_protected += wt
            else:
                self.cwt_flagged_non_protected += wt

        if patient.overbooked:
            if patient.protected:
                self.cwt_stacked_protected += wt
            else:
                self.cwt_stacked_non_protected += wt

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
                        self.original_overbooked_slots[
                            (server_idx, dia_idx, slot_idx)
                        ] = {
                            "anchor": occupants[0],
                            "stackers": occupants[1:],
                        }
                        for stacker_id in occupants[1:]:
                            if self.patients_list[stacker_id].protected:
                                self.protected_overbooked_assigned += 1
                            else:
                                self.non_protected_overbooked_assigned += 1

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
        for (_, _, _), members in self.original_overbooked_slots.items():
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
            if patient.overbooked_target:
                if patient.protected:
                    self.cr_flagged_protected += 1
                else:
                    self.cr_flagged_non_protected += 1

            if patient.overbooked:
                if patient.protected:
                    self.cr_stacked_protected += 1
                else:
                    self.cr_stacked_non_protected += 1

    def _attending_from_slot_list(self, server_idx, dia_idx, slot_idx):
        """
        Return list of attending patient IDs from the current slot list,
        sorted by (num_slot, overbooked_target).
 
        Every patient in the slot list who attends is always a candidate,
        regardless of displacement_offset. The N-slot rule governs where
        they go AFTER displacement, not whether they participate here.
        """
        slot = self.appointments[server_idx][dia_idx][slot_idx]
        attending = [
            pid for pid in slot
            if pid is not None and self.patients_list[pid].attendance
        ]
        attending.sort(key=lambda pid: (
            self.patients_list[pid].num_slot,
            self.patients_list[pid].overbooked_target,
        ))
        return attending

    def _eligible_pending(self, slot_idx, pending_stackers):
        """
        Return pending-buffer stackers whose N-slot wait is fulfilled at
        slot_idx (slot_idx >= stacker.num_slot + N), sorted by num_slot.
 
        Used when the primary pool is non-empty — only fulfilled pending
        stackers join the candidate pool in that case.
        """
        N = self.displacement_offset
        eligible = [
            pid for pid in pending_stackers
            if slot_idx >= self.patients_list[pid].num_slot + N
        ]
        eligible.sort(key=lambda pid: self.patients_list[pid].num_slot)
        return eligible
 
    def _slot_has_attending_patient(self, server_idx, dia_idx, slot_idx):
        """
        True if any patient currently in the slot list will attend.
        Used to detect idle intermediate slots during the N-slot scan.
        Includes both originally scheduled patients and cascade arrivals.
        Does NOT include pending-buffer stackers (not yet in any slot list).
        """
        slot = self.appointments[server_idx][dia_idx][slot_idx]
        return any(
            self.patients_list[pid].attendance
            for pid in slot
            if pid is not None
        )

    def simulation(self):
        self._snapshot_original_overbookings()
 
        N = self.displacement_offset
 
        for server_idx, server in enumerate(self.appointments):
            for dia_idx, dia in enumerate(server):
 
                # Per-day pending buffer.
                # Holds stackers displaced N slots who have not yet been
                # committed to a specific future slot. Checked at every slot
                # for idle-intermediate serving and N-fulfillment serving.
                pending_stackers = []
 
                for slot_idx, slot in enumerate(dia):
 
                    day_length = len(dia)
                    is_last_slot = (slot_idx == day_length - 1)
 
                    # -- Count no-shows for scheduled patients in this slot -
                    # Done before any serving so the count is always accurate.
                    for pid in slot:
                        if pid is not None and not self.patients_list[pid].attendance:
                            self.no_shows += 1
 
                    # -- Build primary candidate pool from slot list --------
                    primary = self._attending_from_slot_list(
                        server_idx, dia_idx, slot_idx
                    )
 
                    # -- Add fulfilled pending stackers when slot not idle --
                    if primary:
                        fulfilled = self._eligible_pending(
                            slot_idx, pending_stackers
                        )
                        # Insert fulfilled pending stackers into primary,
                        # maintaining sort order by (num_slot, overbooked_target).
                        # Fulfilled stackers have num_slot < slot_idx so they
                        # sort before the slot's own patients naturally.
                        ids = sorted(
                            primary + fulfilled,
                            key=lambda pid: (
                                self.patients_list[pid].num_slot,
                                self.patients_list[pid].overbooked_target,
                            )
                        )
                        # Remove fulfilled pending from buffer
                        for pid in fulfilled:
                            pending_stackers.remove(pid)

                        self.n_fulfilled_served += len(fulfilled)

                    else:
                        ids = []
 
                    # -- Idle slot: serve earliest pending stacker ---------
                    # When primary pool (slot list attending + fulfilled pending)
                    # is empty, the slot is idle. Serve the earliest pending
                    # stacker regardless of N-fulfillment.
                    if not ids:
                        if pending_stackers:
                            pending_stackers.sort(
                                key=lambda pid: self.patients_list[pid].num_slot
                            )
                            pid_serve = pending_stackers.pop(0)
                            self.idle_rule_served += 1
                            self._record_attendance(pid_serve, slot_idx)
                        else:
                            self.idle_time_server[server_idx] += self.slot_time
                        continue
 
                    # -- Update slot list to attending candidates -----------
                    self.appointments[server_idx][dia_idx][slot_idx] = ids[:]
 
                    # -- One candidate: serve and done ---------------------
                    if len(ids) == 1:
                        self._record_attendance(ids[0], slot_idx)
                        continue
 
                    # -- Multiple candidates -------------------------------
                    if is_last_slot:
                        # Overtime: serve all candidates then flush pending.
                        # Pending stackers join the end of the queue in
                        # num_slot order — they were waiting for a future
                        # slot that no longer exists.
                        # Merge ids and all remaining pending stackers into a
                        # single list sorted by the unified rule (num_slot,
                        # overbooked_target). This applies the same ordering
                        # principle everywhere — pending stackers with an
                        # earlier original slot interleave before the slot's
                        # own anchor/stacker, not appended after them.
                        all_overtime = sorted(
                            ids + list(pending_stackers),
                            key=lambda pid: (
                                self.patients_list[pid].num_slot,
                                self.patients_list[pid].overbooked_target,
                            )
                        )
                        pending_stackers.clear()
 
                        self.over_time[server_idx] += (
                            self.slot_time * (len(all_overtime) - 1)
                        )
                        for i, pid in enumerate(all_overtime):
                            self._record_attendance(pid, slot_idx + i)
 
                    else:
                        # -- Cascade branch --------------------------------
                        # ids[0] served here. ids[1:] displaced forward.
                        self._record_attendance(ids[0], slot_idx)
                        self.appointments[server_idx][dia_idx][slot_idx] = [
                            ids[0]
                        ]
 
                        for pid in ids[1:]:
                            patient = self.patients_list[pid]
 
                            is_original_stacker = (
                                patient.overbooked
                                and patient.num_slot == slot_idx
                                and not patient.displaced_once
                            )
 
                            if is_original_stacker and N > 1:
                                # First N-slot displacement: enter pending buffer.
                                # The buffer handles idle-intermediate landing
                                # and N-fulfillment serving at future slots.
                                patient.displaced_once = True
                                pending_stackers.append(pid)
 
                            else:
                                # Standard +1 cascade push:
                                #   - N=1 original stacker (same as current behavior)
                                #   - Anchors bumped by cascade arrivals
                                #   - Cascade patients bumped again
                                #   - Stackers already displaced once
                                if is_original_stacker and N == 1:
                                    patient.displaced_once = True
                                next_existing = [
                                    p for p in
                                    self.appointments[server_idx][dia_idx][slot_idx + 1]
                                    if p is not None
                                ]
                                self.appointments[server_idx][dia_idx][slot_idx + 1] = (
                                    [pid] + next_existing
                                )
 
        self._compute_conflict_metrics()
 
    def not_null(self, lista):
        return max(len(lista) - lista.count(None), 0)
 
    def get_measures(self):
        total_waiting_time = self.cwt_protected + self.cwt_non_protected

        total_displacement_events = self.idle_rule_served + self.n_fulfilled_served

        flagged_protected_attendees = sum(
            1 for p in self.patients_list
            if p.attendance and p.assigned and p.overbooked_target and p.protected
        )
        flagged_non_protected_attendees = sum(
            1 for p in self.patients_list
            if p.attendance and p.assigned and p.overbooked_target and not p.protected
        )

        stacked_protected_attendees = sum(
            1 for p in self.patients_list
            if p.attendance and p.assigned and p.overbooked and p.protected
        )
        stacked_non_protected_attendees = sum(
            1 for p in self.patients_list
            if p.attendance and p.assigned and p.overbooked and not p.protected
        )

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

            "cwt_flagged_protected":     self.cwt_flagged_protected,
            "cwt_flagged_non_protected": self.cwt_flagged_non_protected,
            "wt_flagged_mean_protected": (
                self.cwt_flagged_protected / flagged_protected_attendees
                if flagged_protected_attendees > 0 else 0
            ),
            "wt_flagged_mean_non_protected": (
                self.cwt_flagged_non_protected / flagged_non_protected_attendees
                if flagged_non_protected_attendees > 0 else 0
            ),

            # True-stacker metrics (overbooked == True). Population is patients
            "cwt_stacked_protected":     self.cwt_stacked_protected,
            "cwt_stacked_non_protected": self.cwt_stacked_non_protected,
            "wt_stacked_mean_protected": (
                self.cwt_stacked_protected / stacked_protected_attendees
                if stacked_protected_attendees > 0 else 0
            ),
            "wt_stacked_mean_non_protected": (
                self.cwt_stacked_non_protected / stacked_non_protected_attendees
                if stacked_non_protected_attendees > 0 else 0
            ),
            "cr_stacked_protected":     self.cr_stacked_protected,
            "cr_stacked_non_protected": self.cr_stacked_non_protected,
            "cr_stacked_rate_protected": (
                self.cr_stacked_protected / stacked_protected_attendees
                if stacked_protected_attendees > 0 else 0
            ),
            "cr_stacked_rate_non_protected": (
                self.cr_stacked_non_protected / stacked_non_protected_attendees
                if stacked_non_protected_attendees > 0 else 0
            ),
            "stacked_protected_attendees":     stacked_protected_attendees,
            "stacked_non_protected_attendees": stacked_non_protected_attendees,

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

            # CRC normalized by overbooked-assigned population.
            # Measures: of patients placed as overbooking stackers, what fraction
            # experienced a real conflict (anchor also attended)?
            "crc_rate_overbooked_protected": (
                self.crc_protected / self.protected_overbooked_assigned
                if self.protected_overbooked_assigned > 0 else 0
            ),
            "crc_rate_overbooked_non_protected": (
                self.crc_non_protected / self.non_protected_overbooked_assigned
                if self.non_protected_overbooked_assigned > 0 else 0
            ),
            "protected_overbooked_assigned":     self.protected_overbooked_assigned,
            "non_protected_overbooked_assigned": self.non_protected_overbooked_assigned,

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

            # CR-flagged: any displacement (waiting_time > 0) restricted
            # to flagged patients (proba > group threshold). Isolates the
            # subset of patients on whom the overbooking rule operates.
            "cr_flagged_protected": self.cr_flagged_protected,
            "cr_flagged_non_protected": self.cr_flagged_non_protected,
            "cr_flagged_rate_protected": (
                self.cr_flagged_protected / flagged_protected_attendees
                if flagged_protected_attendees > 0 else 0
            ),
            "cr_flagged_rate_non_protected": (
                self.cr_flagged_non_protected / flagged_non_protected_attendees
                if flagged_non_protected_attendees > 0 else 0
            ),
            "flagged_protected_attendees":     flagged_protected_attendees,
            "flagged_non_protected_attendees": flagged_non_protected_attendees,

            # Displacement diagnostics
            # idle_rule_served: pending stackers absorbed at idle slots
            #   before N-wait elapsed. High values mean the N penalty is
            #   being short-circuited by no-shows in intermediate slots.
            # n_fulfilled_served: pending stackers who waited the full N
            #   slots. High values mean N is being applied in full.
            # idle_absorption_rate: fraction of displacement events resolved
            #   by the idle rule. Near 1.0 → N has little WT effect.
            #   Near 0.0 → N is fully applied.
            "idle_rule_served":      self.idle_rule_served,
            "n_fulfilled_served":    self.n_fulfilled_served,
            "idle_absorption_rate": (
                self.idle_rule_served / total_displacement_events
                if total_displacement_events > 0 else 0
            ),
        }
        return measures
