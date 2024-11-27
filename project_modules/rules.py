from project_modules.project_imports import *
from project_modules.classes import Patient, Clinic

def call_a_rule (patient_list, appointments, name_rule, ml_model, threshold_protected, threshold_no_protected, overbooking):
    
    refused_patients=0
    num_protected=0
    num_no_protected=0
    
    # Determinar procedimiento a usar segun rule name
    for patient in patient_list:
        if name_rule=='fcfa':
            appointments = fcfa(patient, appointments)
        elif name_rule=='overbooking_simple':
            appointments = rule_overbooking(patient, appointments, threshold_protected, threshold_no_protected, overbooking, ml_model )
        
        # elif name_rule=='overbooking_high_proba':
        #     appointments = rule_overbooking_high(patient,patient_list, appointments, threshold_protected, threshold_no_protected, overbooking, ml_model )
        # elif name_rule=='low_probability':
        #     appointments = low_probability(patient, appointments, threshold_protected, threshold_no_protected, patient_list, ml_model)
        
        elif name_rule=='fountain_overbooking':
            appointments = fountain_overbooking(patient,patient_list, appointments, threshold_protected,threshold_no_protected,overbooking, ml_model)
        elif name_rule=='ATBEG':
            appointments = ATBEG(patient, appointments, 
                                 threshold_protected, threshold_no_protected, 
                                 overbooking, 
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

def rule_overbooking(patient, appointments, threshold_protected,threshold_no_protected,nivel_overbooking ,train_model):

    # Establece si un paciente si le puede hacer overbooking segun su probabilidad (ALTA)

    # Predice proba de inasistencia con el respectivo modelo
    # patient.predict_proba(train_model)
    
    patient.overbooked = False

    # Decide si overbook o no basado en la prediccion
    if patient.protected==True:
        overbook=True if patient.proba>threshold_protected else False
    else:
        overbook=True if patient.proba>threshold_no_protected else False

    if overbook:
        patient.overbooked=True
    
    # Si el paciente aun no se ha asignado 
    if not patient.assigned:

        start_day=patient.day_of_call
        
        # el dia final es el ultimo de la ventana de tiempo 
        # end_day=min(patient.day_of_call+6,len(appointments[0]))
        end_day=len(appointments[0])
        
        # Itera desde el dia que llama hasta el final
        for dia in range(start_day, end_day):

            # Itera sobre los slots del dia
            if not patient.assigned:
                for slot in range(len(appointments[0][dia])):
                    for server in range(len(appointments)):        
                        # Itera dentro de los slots para revisar asignaciones
                        for id in range(len(appointments[server][dia][slot])):
                            if overbook:
                                # Overbook si hay exactamente un paciente en ese slot
                                if appointments[server][dia][slot][id] is not None and len(appointments[server][dia][slot])==1:
                                    appointments[server][dia][slot].append(patient.id)
                                    patient.num_slot = slot
                                    patient.assigned = True
                                    return appointments

            # Si aun no se asigna es porque no se debe hacer overbooking
            if not patient.assigned:
                for slot in range(len(appointments[0][dia])):
                    for server in range(len(appointments)):        
                        for id in range(len(appointments[server][dia][slot])):
                            # asigna en un slot vacio (no overbooking)
                            if appointments[server][dia][slot][id] is  None :
                                appointments[server][dia][slot][id]= patient.id
                                patient.num_slot=slot
                                patient.assigned=True
                                return appointments
    
    return appointments

# K primeros overbooking y overbooking a los de alta probabilidad
def fountain_overbooking(patient, patient_list, appointments, threshold_protected,threshold_no_protected, nivel_overbooking, train_model):
    
    patient.overbooked = False
    overbook=False

    # Predice proba de inasistencia con el respectivo modelo
    # patient.predict_proba(train_model)
    
    # Decide si overbook o no basado en la prediccion
    if patient.protected==True:
        overbook=True if patient.proba>threshold_protected else False
    else:
        overbook=True if patient.proba>threshold_no_protected else False

    if overbook:
        patient.overbooked = True
    
    initial_over = 5
    
    # Si el paciente aun no se ha asignado 
    if not patient.assigned:

        start_day=patient.day_of_call
        
        # el dia final es el ultimo de la ventana de tiempo 
        end_day=len(appointments[0])
        
        # Itera desde el dia que llama hasta el final
        for dia in range(start_day, end_day):
            # Asignaciones fijas de overbooking
            for i in range(0, initial_over):
                if appointments[0][dia][i][0] is None:
                    appointments[0][dia][i][0] = patient.id
                    patient.num_slot=i
                    patient.overbooked=True
                    patient.assigned=True
                    return appointments
                
            # Itera sobre los slots del dia
            if not patient.assigned:
                if overbook:
                    # for slot in range(len(appointments[0][dia])):
                    #     for server in range(len(appointments)):        
                    for server in range(len(appointments)): 
                        for slot in range(len(appointments[server][dia])):
                            # Itera dentro de los slots para revisar asignaciones
                            for id in range(len(appointments[server][dia][slot])):
                                #if overbook:
                                # Overbook si hay exactamente un paciente en ese slot
                                if appointments[server][dia][slot][id] is not None and len(appointments[server][dia][slot])==1:
                                    if patient_list[appointments[server][dia][slot][id]].overbooked == True:
                                        
                                        appointments[server][dia][slot].append(patient.id)
                                        # patient.overbooked = True
                                        patient.num_slot = slot
                                        patient.assigned = True
                                        return appointments
                                              
            # Si aun no se asigna es porque no se debe hacer overbooking
            if not patient.assigned:
                for slot in range(len(appointments[0][dia])):
                    for server in range(len(appointments)):        
                        for id in range(len(appointments[server][dia][slot])):
                            # asigna en un slot vacio (no overbooking)
                            if appointments[server][dia][slot][id] is  None :
                                
                                appointments[server][dia][slot][id]= patient.id
                                patient.num_slot=slot
                                patient.assigned=True
                                if appointments[server][dia][slot][id] is  None :
                                    print("No se guardo el valor para patient id {}".format(patient.id))
                                   
                                    appointments[server][dia][slot][id]= patient.id
                                return appointments
    
    return appointments

def ATBEG(patient, appointments,
          threshold_protected, threshold_no_protected, 
          nivel_overbooking, 
          train_model):
    # Predice proba de inasistencia con el respectivo modelo
    patient.predict_proba(train_model)

    """
    Asignacion del paciente haciendo overbooking cada 3 slots, teniendo de base un paciente no overbooked en el primer slot 
    De resalpado un high probability 

    Returns:
        _type_: _description_
    """

    # Decide si overbook o no basado en la prediccion
    if patient.protected==True:
        overbook=True if patient.proba>threshold_protected else False
    else:
        overbook=True if patient.proba>threshold_no_protected else False


    if not patient.assigned:
        start_day=patient.day_of_call
        #print(len(appointments[0]))
        end_day=len(appointments[0])
        for dia in range(start_day, end_day):
            # Si el paciente no se le puede hacer overbooking buscara asignarlo de primera instancia en un slot vacio de los de overbooking
            if overbook==False:
                for slot in range(0,len(appointments[0][dia]),nivel_overbooking):
                    for server in range(len(appointments)):        
                            if appointments[server][dia][slot][0] is  None :
                                appointments[server][dia][slot][0]= patient.id
                                patient.num_slot=slot
                                patient.assigned=True
                                patient.overbooked=True
                                return appointments
                # Si despues de revisar en ese dia no encontro un espacio disponibile en los slots de overbooking, 
                # como primer paciente lo hara en el primer slot vacio que encuentre 
                for slot in range(len(appointments[0][dia])):
                        for server in range(len(appointments)):        
                            for id in range(len(appointments[server][dia][slot])):
                                # asigna en un slot vacio (no overbooking)
                                if appointments[server][dia][slot][id] is  None :
                                    appointments[server][dia][slot][id]=patient.id
                                    patient.num_slot=slot
                                    patient.assigned=True
                                    return appointments    
            else:# High probability - assing patient in the first slot del primero a la segunda posicion
                for dia in range(start_day, end_day):
                    for slot in range(0,len(appointments[0][dia]),nivel_overbooking):
                        for server in range(len(appointments)):        
                            for id in range(len(appointments[server][dia][slot])):
                                if len(appointments[server][dia][slot]) == 1:
                                    appointments[server][dia][slot].append(patient.id)
                                    patient.num_slot=slot
                                    patient.assigned=True
                                    patient.overbooked=True
                                    return appointments
                for slot in range(len(appointments[0][dia])): # Puede pasar que en un slot queden dos de alta probabilidad
                        for server in range(len(appointments)):        
                            for id in range(len(appointments[server][dia][slot])):
                                # asigna en un slot vacio (no overbooking)
                                if appointments[server][dia][slot][id] is  None :
                                    appointments[server][dia][slot][id]= patient.id
                                    patient.num_slot=slot
                                    patient.assigned=True
                                    # patient.overbooked=True
                                    return appointments 
    return appointments                  


def get_proba_matrix(patient, appointments,model,threshold):
    """Objetivo calcular la matriz de probabilidad solo una vez al principio y solo con los slot disponible 
    # Retorna una matriz de probabilidad con todos los slots disponibles
    # Retorna proba_global que es donde se encuentra disponibile y es la menor probabilidad
    # Retorna proba_filled que es donde se encuentra ocupado y es la menor probabilidad
    Args:
        patient (Paciente): _description_
        appointments (_type_): _description_
        model (_type_): _description_
        threshold (_type_): _description_

    Returns:
        _type_: _description_
    """
    proba_global={"proba":1000,"server":None,"dia":None,"slot":None}
    proba_filled={"proba":1000,"server":None,"dia":None,"slot":None}
    # Get the dimensions
    length1 = len(appointments)# serves
    length2 = len(appointments[0])#days
    length3 = len(appointments[0][0])#slots
    overbook=False
    cont_overbook=0

    # Create the NumPy array filled with zeros
    proba_matrix = np.ones((length1, length2, length3), dtype=float)
    dia_inicio=patient.day_of_call
    for server in range(len(appointments)):
        for dia in range(dia_inicio,len(appointments[server])):
            for slot in range(len(appointments[server][dia])):
                    if appointments[server][dia][slot][0] is None:
                        patient.real_lead_time=(dia+(slot/len(appointments[server][dia])))-patient.day_of_call 
                        proba_new=patient.predict_proba(model)
                        proba_matrix[server,dia,slot] = proba_new
                        if proba_new>threshold and dia < 3 :
                             cont_overbook+=1
                        if proba_new<proba_global["proba"]:
                            proba_global={"proba":proba_new,"server":server,"dia":dia,"slot":slot}
                    else:
                        patient.real_lead_time=(dia+(slot/len(appointments[server][dia])))-patient.day_of_call
                        proba_new=patient.predict_proba(model)
                        if proba_new>threshold and dia < 3 :
                             cont_overbook+=1
                        proba_matrix[server,dia,slot] = proba_new
                        if proba_new<proba_filled["proba"]:
                            proba_filled={"proba":proba_new,"server":server,"dia":dia,"slot":slot} 
    if cont_overbook>2*len(appointments[0])*len(appointments)*0.6:
         overbook=True
    return proba_matrix, proba_global, proba_filled, overbook

def low_probability(patient, appointments,threshold_protected,threshold_no_protected, general_list,train_model):
    print(type(appointments))
    proba_matrix, best_proba, filled_proba,over = get_proba_matrix(patient,appointments,train_model,0.4)
    """_summary_

    Returns:
        _type_: _description_
    """
    threshold=threshold_no_protected if patient.protected==False else threshold_protected
    # 1. Reviso si el lugar con menor probabilidad esta vacio para ubicarlo en ese lugar

    if best_proba["server"] is None and best_proba["proba"]<threshold:
        appointments[best_proba["server"]][best_proba["dia"]][best_proba["slot"]][0]=patient.id
        patient.assigned=True

    # 2. Si no fue asignado, 
    if not patient.assigned:
        start_day=patient.day_of_call
        #end_day=min(patient.day_of_call+6,len(appointments[0]))
        end_day=len(appointments[0])
        for dia in range(start_day,end_day):
            if not patient.assigned:
                for server in range(len(appointments)):
                    #Revisa el primer dia para no afectar su leadtime indirecto en el sistema
                    if over:
                        for slot in range(len(appointments[0][dia])):
                            for server in range(len(appointments)):        
                                for id in range(len(appointments[server][dia][slot])):
                                    if appointments[server][dia][slot][id] is not None and len(appointments[server][dia][slot])==1:
                                    # Asignar a dos pacientes con alta probabilidad
                                        if general_list[appointments[server][dia][slot][0]].proba>threshold and proba_matrix[server,dia,slot]>threshold:
                                            patient.proba=proba_matrix[server,dia,slot]
                                            appointments[server][dia][slot].append(patient.id)
                                            patient.num_slot=slot
                                            patient.assigned=True
                                            break
                                        else :
                                            appointments[server][dia][slot][id]= patient.id
                                            patient.num_slot=slot
                                            patient.assigned=True
                                            break
                                    if patient.assigned:
                                        break
                                if patient.assigned:
                                    break
                            if patient.assigned:
                                break
                else:
                    for slot in range(len(appointments[0][dia])):
                        for server in range(len(appointments)):        
                            for id in range(len(appointments[server][dia][slot])):
                                if appointments[server][dia][slot][id] is  None :
                                    appointments[server][dia][slot][id]= patient.id
                                    patient.num_slot=slot
                                    patient.assigned=True
                                    break
                                if patient.assigned:
                                    break
                            if patient.assigned:
                                break
                        if patient.assigned:
                            break
                    if patient.assigned:
                        break
                if patient.assigned:
                    break
            else:
                break
    return appointments

def rule_overbooking_high(patient,patient_list, appointments, threshold_protected,threshold_no_protected,nivel_overbooking, train_model):
    ####################### EN CONSTRUCCION
    # Establece si un paciente si le puede hacer overbooking segun su probabilidad (ALTA)
    # Predice proba de inasistencia con el respectivo modelo
    # patient.predict_proba(train_model)

    patient.overbooked = False
    
    # Decide si overbook o no basado en la prediccion
    if patient.protected==True:
        overbook=True if patient.proba>threshold_protected else False
    else:
        overbook=True if patient.proba>threshold_no_protected else False

    if overbook:
        patient.overbooked = True
    

    # Si el paciente aun no se ha asignado 
    if not patient.assigned:

        start_day=patient.day_of_call
        
        # el dia final es el ultimo de la ventana de tiempo 
        end_day=len(appointments[0])
        # Itera desde el dia que llama hasta el final
        for dia in range(start_day, end_day):
            # Itera sobre los slots del dia
            if not patient.assigned:
                if overbook:
                    for slot in range(len(appointments[0][dia])):
                        for server in range(len(appointments)):        
                            # Itera dentro de los slots para revisar asignaciones
                            for id in range(len(appointments[server][dia][slot])):
                                #if overbook:
                                    # Overbook si hay exactamente un paciente en ese slot
                                    if appointments[server][dia][slot][id] is not None and len(appointments[server][dia][slot])==1:
                                        if patient_list[appointments[server][dia][slot][id]].overbooked == True:
                                            appointments[server][dia][slot].append(patient.id)
                                            patient.overbooked = True
                                            patient.num_slot = slot
                                            patient.assigned = True
                                            return appointments
            # Si aun no se asigna es porque no se debe hacer overbooking
            if not patient.assigned:
                for slot in range(len(appointments[0][dia])):
                    for server in range(len(appointments)):        
                        for id in range(len(appointments[server][dia][slot])):
                            # asigna en un slot vacio (no overbooking)
                            if appointments[server][dia][slot][id] is  None :
                                appointments[server][dia][slot][id]= patient.id
                                patient.num_slot=slot
                                patient.assigned=True
                                return appointments
    return appointments