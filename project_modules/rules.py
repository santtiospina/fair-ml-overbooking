# project_modules/rules.py
from project_modules.project_imports import *
from project_modules.classes import Patient, Clinic

def call_a_rule (patient_list, appointments, name_rule, ml_model, threshold_protected, threshold_no_protected, overbooking_level):
    
    refused_patients=0
    num_protected=0
    num_no_protected=0
    
    # Determinar procedimiento a usar segun rule name
    for patient in patient_list:
        if name_rule=='fcfa':
            appointments = fcfa(patient, appointments)
        elif name_rule=='overbooking_simple':
            appointments = rule_overbooking(patient, appointments, threshold_protected, threshold_no_protected, overbooking_level, ml_model )
        
        elif name_rule=='fountain':
            appointments = fountain_overbooking(patient, patient_list, 
                                                appointments, 
                                                threshold_protected, threshold_no_protected,
                                                overbooking_level,
                                                ml_model)
        else:
            print("Unknown name_rule")
        if not patient.assigned:
                        #print(f"Patient {patient.id} could not be assigned within the next {simulation_days} days")
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

            # ── Branch A: Try real overbooking (stack onto an existing booking) ──
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

            # ── Branch B: Fallback to an empty slot (NOT overbooking) ──
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

def fountain_overbooking(patient, patient_list, appointments,
                         threshold_protected, threshold_no_protected,
                         nivel_overbooking, train_model):

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

            # ── Branch A: Fountain primary assignment (NOT overbooking) ──
            # First `nivel_overbooking` empty slots of the day get filled regardless of eligibility.
            # These are single-patient slots — no conflict — so overbooked stays False.
            for i in range(0, nivel_overbooking):
                if appointments[0][dia][i][0] is None:
                    appointments[0][dia][i][0] = patient.id
                    patient.num_slot = i
                    patient.assigned = True
                    # patient.overbooked stays False ← key fix
                    return appointments

            # ── Branch B: Real overbooking (stack onto an existing eligible patient) ──
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

            # ── Branch C: Fallback to any empty slot (NOT overbooking) ──
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