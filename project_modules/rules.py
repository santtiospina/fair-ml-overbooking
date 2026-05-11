# project_modules/rules.py
from project_modules.project_imports import *
from project_modules.classes import Patient, Clinic

def call_a_rule(
    patient_list,
    appointments,
    name_rule,
    ml_model,
    threshold_protected,
    threshold_no_protected,
    overbooking_level,
    min_stack_slot=0,
):
    refused_patients = 0
    for patient in patient_list:
        if name_rule == 'fcfa':
            appointments = fcfa(patient, appointments)
        elif name_rule == 'overbooking_simple':
            appointments = rule_overbooking(
                patient,
                appointments,
                threshold_protected,
                threshold_no_protected,
                overbooking_level,
                ml_model
            )
        elif name_rule == 'fountain':
            appointments = fountain_overbooking(
                patient,
                patient_list,
                appointments,
                threshold_protected,
                threshold_no_protected,
                overbooking_level,
            )
        elif name_rule == 'simple_pairing':
            appointments = rule_simple_pairing(
                patient,
                patient_list,
                appointments,
                threshold_protected,
                threshold_no_protected,
                overbooking_level,
                min_stack_slot,
            )
        elif name_rule == 'flagged_pairing':
            appointments = rule_flagged_pairing(
                patient,
                patient_list,
                appointments,
                threshold_protected,
                threshold_no_protected,
                overbooking_level,
                min_stack_slot,
            )
        else:
            print("Unknown name_rule")

        if not patient.assigned:
            refused_patients += 1
    return appointments, refused_patients

def fcfa(patient, appointments):
    if not patient.assigned:
        for server in range(len(appointments)):
            start_day = patient.day_of_call
            end_day = min(patient.day_of_call + 6, len(appointments[server]))
            for dia in range(start_day, end_day):
                for slot in range(len(appointments[server][dia])):
                    for id in range(len(appointments[server][dia][slot])):
                        if appointments[server][dia][slot][id] is None:
                            appointments[server][dia][slot][id] = patient.id
                            patient.num_slot=slot
                            patient.assigned = True
                            return appointments
    return appointments

def rule_overbooking(patient, appointments, threshold_protected, threshold_no_protected, nivel_overbooking, train_model):
    # Reset flags (defensive, in case patient is reused)
    patient.overbooked = False
    patient.overbooked_target = False

    # Determine eligibility based on probability threshold
    if patient.protected:
        overbook_eligible = patient.proba > threshold_protected
    else:
        overbook_eligible = patient.proba > threshold_no_protected

    # Record eligibility (intent to overbook) — separate from actual conflict
    patient.overbooked_target = overbook_eligible

    if not patient.assigned:
        start_day = patient.day_of_call
        end_day = len(appointments[0])

        for dia in range(start_day, end_day):

            # -- Branch A: Try real overbooking (stack onto an existing booking) --
            # Only eligible patients attempt this. patient.overbooked becomes True
            # ONLY if the stack actually happens.
            if overbook_eligible and not patient.assigned:
                for slot in range(len(appointments[0][dia])):
                    for server in range(len(appointments)):
                        for id in range(len(appointments[server][dia][slot])):
                            if (appointments[server][dia][slot][id] is not None
                                    and len(appointments[server][dia][slot]) == 1):
                                appointments[server][dia][slot].append(patient.id)
                                patient.num_slot = slot
                                patient.overbooked = True   # real conflict: TRUE
                                patient.assigned = True
                                return appointments

            # -- Branch B: Fallback to an empty slot (NOT overbooking) --
            # patient.overbooked stays False — no conflict occurred.
            if not patient.assigned:
                for slot in range(len(appointments[0][dia])):
                    for server in range(len(appointments)):
                        for id in range(len(appointments[server][dia][slot])):
                            if appointments[server][dia][slot][id] is None:
                                appointments[server][dia][slot][id] = patient.id
                                patient.num_slot = slot
                                patient.assigned = True
                                # patient.overbooked stays False ← key fix
                                return appointments
    return appointments

def fountain_overbooking(
    patient,
    patient_list,
    appointments,
    threshold_protected,
    threshold_no_protected,
    nivel_overbooking,
):

    # Reset flags
    patient.overbooked = False
    patient.overbooked_target = False

    # Determine eligibility
    if patient.protected:
        overbook_eligible = patient.proba > threshold_protected
    else:
        overbook_eligible = patient.proba > threshold_no_protected

    # Record eligibility — THIS is what the stacking branch below checks against
    patient.overbooked_target = overbook_eligible

    if not patient.assigned:
        start_day = patient.day_of_call
        end_day = len(appointments[0])

        for dia in range(start_day, end_day):

            # -- Branch A: Fountain primary assignment (NOT overbooking) --
            # First `nivel_overbooking` empty slots of the day get filled regardless of eligibility.
            # These are single-patient slots — no conflict — so overbooked stays False.
            for i in range(0, nivel_overbooking):
                if appointments[0][dia][i][0] is None:
                    appointments[0][dia][i][0] = patient.id
                    patient.num_slot = i
                    patient.assigned = True
                    # patient.overbooked stays False ← key fix
                    return appointments

            # -- Branch B: Real overbooking (stack onto an existing eligible patient) --
            # Only eligible patients stack, and only onto other eligible patients.
            if not patient.assigned and overbook_eligible:
                for server in range(len(appointments)):
                    for slot in range(len(appointments[server][dia])):
                        for id in range(len(appointments[server][dia][slot])):
                            if (appointments[server][dia][slot][id] is not None
                                    and len(appointments[server][dia][slot]) == 1):
                                # Check if the existing patient was flagged as an overbooking target
                                existing_patient_id = appointments[server][dia][slot][id]
                                if patient_list[existing_patient_id].overbooked_target:
                                    appointments[server][dia][slot].append(patient.id)
                                    patient.num_slot = slot
                                    patient.overbooked = True   # real conflict: TRUE
                                    patient.assigned = True
                                    return appointments

            # -- Branch C: Fallback to any empty slot (NOT overbooking) --
            if not patient.assigned:
                for slot in range(len(appointments[0][dia])):
                    for server in range(len(appointments)):
                        for id in range(len(appointments[server][dia][slot])):
                            if appointments[server][dia][slot][id] is None:
                                appointments[server][dia][slot][id] = patient.id
                                patient.num_slot = slot
                                patient.assigned = True
                                # patient.overbooked stays False ← key fix
                                return appointments

    return appointments

def rule_simple_pairing(
    patient,
    patient_list,
    appointments,
    threshold_protected,
    threshold_no_protected,
    nivel_overbooking,
    min_stack_slot=0,
):
    """
    Simple pairing overbooking rule with a per-day cap.

    Mechanism:
      - A patient is "flagged" if their predicted no-show probability
        exceeds the group-specific threshold.
      - A flagged patient stacks onto an existing single-booked slot
        whose occupant is NON-flagged (predicted to attend).
      - When the flagged patient *does* attend (false positive), a true
        conflict occurs. Lower-PPV groups have more false positives,
        so they accumulate more conflict-driven waiting time.

    Per-day cap:
      `nivel_overbooking` = maximum number of stacked slots per day,
      counted globally across all servers.

    min_stack_slot:
    The first `min_stack_slot` slots of each day are excluded from Step 1
    (stacking). Step 2 (anchor placement) is unaffected — anchors still
    fill from slot 0 as normal. Setting min_stack_slot > 0 places conflicts
    later in the day, reducing cascade depth and end-of-day overtime.
    Default 0 preserves the original behavior.

    Assignment priority per day:
      1. If flagged AND day's cap not reached → try to pair with a
         non-flagged single-booked occupant.
      2. Otherwise → take the first empty slot.
    """
    # Reset state
    patient.overbooked = False
    patient.overbooked_target = False
 
    if patient.protected:
        flagged = patient.proba > threshold_protected
    else:
        flagged = patient.proba > threshold_no_protected
 
    patient.overbooked_target = flagged
 
    if patient.assigned:
        return appointments
 
    start_day = patient.day_of_call
    end_day = len(appointments[0])
 
    for dia in range(start_day, end_day):
 
        # -- Step 1: flagged patient stacks onto a non-flagged slot ----------
        if flagged:
            # Recompute paired count from actual slot state — always exact.
            paired_today = sum(
                1
                for server in range(len(appointments))
                for slot_list in appointments[server][dia]
                if sum(1 for pid in slot_list if pid is not None) >= 2
            )
 
            if paired_today < nivel_overbooking:
                for slot in range(min_stack_slot, len(appointments[0][dia])):
                    for server in range(len(appointments)):
                        current = appointments[server][dia][slot]
                        if (len(current) == 1
                                and current[0] is not None
                                and not patient_list[current[0]].overbooked_target):
                            current.append(patient.id)
                            patient.num_slot = slot
                            patient.overbooked = True
                            patient.assigned = True
                            return appointments
 
        # -- Step 2: fallback to the first empty slot ------------------------
        # Also reached by flagged patients when cap is hit or no eligible
        # partner exists. In that case overbooked stays False.
        for slot in range(len(appointments[0][dia])):
            for server in range(len(appointments)):
                if appointments[server][dia][slot][0] is None:
                    appointments[server][dia][slot][0] = patient.id
                    patient.num_slot = slot
                    patient.assigned = True
                    return appointments
 
    return appointments

def rule_flagged_pairing(
    patient,
    patient_list,
    appointments,
    threshold_protected,
    threshold_no_protected,
    nivel_overbooking,
    min_stack_slot=0,
):
    """
    Flagged-onto-flagged pairing overbooking rule with a per-day cap.

    Mechanism:
      - A patient is "flagged" if their predicted no-show probability
        exceeds the group-specific threshold.
      - A flagged patient stacks onto an existing single-booked slot
        whose occupant is ALSO flagged.
      - A real conflict at an originally-overbooked slot occurs only
        when BOTH flagged patients attend, i.e. when both are false
        positives. The per-slot conflict probability is therefore
        (1 - PPV_anchor) * (1 - PPV_stacker), which is much lower than
        the (1 - PPV) * NPV of the non-flagged-onto-flagged rule but
        amplifies the per-slot disparity between groups when both
        slot occupants belong to the same group.

    Per-day cap:
      `nivel_overbooking` = maximum number of stacked slots per day,
      counted globally across all servers.

    min_stack_slot:
    The first `min_stack_slot` slots of each day are excluded from Step 1
    (stacking). Step 2 (anchor placement) is unaffected — anchors still
    fill from slot 0 as normal. Setting min_stack_slot > 0 places conflicts
    later in the day, reducing cascade depth and end-of-day overtime.
    Default 0 preserves the original behavior.

    Assignment priority per day:
      1. If flagged AND day's cap not reached → try to pair with a
         flagged single-booked occupant.
      2. Otherwise → take the first empty slot.
         (Non-flagged patients always take this path.)
    """
    # Reset state
    patient.overbooked = False
    patient.overbooked_target = False

    if patient.protected:
        flagged = patient.proba > threshold_protected
    else:
        flagged = patient.proba > threshold_no_protected

    patient.overbooked_target = flagged

    if patient.assigned:
        return appointments

    start_day = patient.day_of_call
    end_day = len(appointments[0])

    for dia in range(start_day, end_day):

        # -- Step 1: flagged patient stacks onto a flagged single-booked slot
        if flagged:
            # Recompute paired count from actual slot state — always exact.
            paired_today = sum(
                1
                for server in range(len(appointments))
                for slot_list in appointments[server][dia]
                if sum(1 for pid in slot_list if pid is not None) >= 2
            )

            if paired_today < nivel_overbooking:
                for slot in range(min_stack_slot, len(appointments[0][dia])):
                    for server in range(len(appointments)):
                        current = appointments[server][dia][slot]
                        if (len(current) == 1
                                and current[0] is not None
                                and patient_list[current[0]].overbooked_target):
                            current.append(patient.id)
                            patient.num_slot = slot
                            patient.overbooked = True
                            patient.assigned = True
                            return appointments

        # -- Step 2: fallback to the first empty slot ------------------------
        # Reached by:
        #   - non-flagged patients (always)
        #   - flagged patients when no flagged partner exists yet
        #   - flagged patients when the day's cap is already filled
        # In all these cases overbooked stays False.
        for slot in range(len(appointments[0][dia])):
            for server in range(len(appointments)):
                if appointments[server][dia][slot][0] is None:
                    appointments[server][dia][slot][0] = patient.id
                    patient.num_slot = slot
                    patient.assigned = True
                    return appointments

    return appointments
