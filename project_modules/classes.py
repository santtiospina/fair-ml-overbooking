from project_modules.project_imports import *

class Patient:
    # patient class with the attributes as the columns of the df
    def __init__(self, id, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
            
        self.id = id
        self.proba = 0
        self.protected = False
        self.attendance = True
        self.assigned = False
        self.day_of_call = 0
        self.num_slot=-1
        self.overbooked = False
        self.waiting_time = 0

        # self.sample_id = -1

        if self.regime_subsidized == 1:
            self.protected = True
            
    def predict_proba(self, model):

        # overbooking_proba_protected = 0.5
        # overbooking_proba_non_protected = 0.5

        # prediccion sobre los atributos del paciente excepto id, predicted_proba y protected
        patient_data = pd.DataFrame([self.__dict__])
        patient_data = patient_data.drop(columns=['id', 'proba', 'protected', 'attendance', 'assigned','day_of_call','num_slot', 'overbooked', 'waiting_time'])

        # positive prediction
        prediction = model.predict_proba(patient_data)[:, -1][0]

        self.proba = prediction

        # define if patient has to be overbooked given its class
        # if self.protected:
        #     if self.proba > overbooking_proba_protected:
        #         self.overbooked = True
        # else:
        #     if self.proba > overbooking_proba_non_protected:
        #         self.overbooked = True

        # print(f"Patient {self.id} predicted probability: {prediction}")
        return prediction
    
    def properties(self):
        print(f"Patient {self.id} properties:")
        print(self.__dict__)

class Clinic:
    def __init__(self, patients_data, appointments,slot_time):
        
        # This is a list of patients to be served by the clinic
        self.appointments = appointments
        self.patients_list = patients_data
        self.slot_time = slot_time # Minutes

        # Metricas de la clinica
        #self.service_time = np.zeros(len(self.appointments))
        self.over_time = np.zeros(len(self.appointments))
        self.no_shows=0
        self.refused_patients=0 
        self.total_time=0
        self.idle_time_server =np.zeros(len(self.appointments)) 

        self.protected_assistance = 0
        self.non_protected_assistance = 0
 
        #Initialize the appointment with array FULL OF 0
        self.appointments=appointments
        
        # inicializando este porque si no daba error
        self.cwt_protected = 0
        self.cwt_non_protected = 0

        #Calcula el CWL, Desde el dia siguiente a ser solicitada la cita hasta el momento de la cita 
    def compute_waiting_time(self, day, slot, id):
        direct_time = 0
        # total_time = 0
        # hora_inicio = 6
        # Diferencia entre slot asignado y slot atendido * tiempo slot (minutos)
        direct_time = (slot - self.patients_list[id].num_slot) * self.slot_time
        
        # # No se esta usando 
        # total_time = int(day-self.patients_list[id].day_of_call+1)
        # total_time = total_time*60*24
        # minutes = (self.slot_time*(slot))+(60*hora_inicio)
        # total_time = total_time+minutes
        # Se puede retornar tambien el tiempo total de espera (a consideracion)
        return max(0,direct_time)
    
    def simulation(self):
        for server_idx, server in enumerate(self.appointments):
            for dia_idx, dia in enumerate(server):
                for slot_idx, slot in enumerate(dia):
                        # si no hay paciente en slot, idle system time
                        if slot.count(None) == 1:# Cambie el simbolo por n == en vez de >        
                                self.idle_time_server[server_idx] += self.slot_time

                                #Agregue esta linea para dejar el slot como vacio
                                #self.appointments[server_idx][dia_idx][slot_idx]=[]
                                continue
                        
                        # Only one patient assigned to the slot
                        if self.not_null(slot)==1:
                            # Assiged patient MISSES APPOINTMENT -> Idle time (slot vacio)
                            if self.patients_list[slot[0]].attendance==False:
                                self.appointments[server_idx][dia_idx][slot_idx]=[]
                                self.idle_time_server[server_idx]+=self.slot_time
                                self.no_shows+=1
                            # Assigned patient shows up
                            else:
                                # aqui estaba definido como patient pero la clinica no sabe que es patient, accede desde la lista de pacientes
                                if self.patients_list[slot[0]].protected == False:
                                # if patient.protected == False:
                                    self.cwt_non_protected += self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.patients_list[slot[0]].waiting_time = self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.non_protected_assistance += 1
                                else:
                                    self.cwt_protected += self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.patients_list[slot[0]].waiting_time = self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.protected_assistance += 1

                                #self.service_time[server_idx]+=self.slot_time
                        
                        # There are no patients assigned to the slot
                        elif self.not_null(slot)==0:
                            if slot.count(None)>0:
                                self.idle_time_server[server_idx]+=self.slot_time
                                continue
                            self.idle_time_server[server_idx]+=self.slot_time
                        
                        # >1 patients assigned to the slot (OVERBOOKING)
                        else:
                            ids=[]
                            # add patients that attended to the ids list
                            for i in range(len(slot)):
                                if self.patients_list[slot[i]].attendance==True:
                                    ids.append(slot[i])
                                else:
                                    self.no_shows+=1
                            self.appointments[server_idx][dia_idx][slot_idx]=ids
                            
                            # More than one patient SHOWS UP
                            if len(ids)>1:
                                
                                # 1.1 Is this the last slot schedule for the day - Si tengo que hacer overtime

                                # Calcular tiempos de espera de los pacientes de overtime
                                if slot_idx==(len(self.appointments[server_idx][dia_idx])-1):
                                    self.over_time[server_idx]+=self.slot_time*(len(ids)-1)

                                    for i in range(len(ids)):
                                        if self.patients_list[slot[i]].protected == False:
                                            self.cwt_non_protected += self.compute_waiting_time(dia_idx, slot_idx+i, ids[i])
                                            self.patients_list[slot[i]].waiting_time = self.compute_waiting_time(dia_idx, slot_idx+i, ids[i])
                                            self.non_protected_assistance += 1
                                        else:
                                            self.cwt_protected += self.compute_waiting_time(dia_idx, slot_idx+i, ids[i])  
                                            self.patients_list[slot[i]].waiting_time = self.compute_waiting_time(dia_idx, slot_idx+i, ids[i])
                                            self.protected_assistance += 1
                                
                                # 1.2 More than one patient SHOW-UP and is not the last slot for the server
                                else:
                                    temp_reasign=slot[1:]
                                    reasign=[]
                                    for i in range(len(temp_reasign)):
                                        if self.patients_list[temp_reasign[i]].attendance==True:
                                             reasign.append(temp_reasign[i])

                                    test = [None]
                                    test[0] = slot[0]
                                    reasign.extend(self.appointments[server_idx][dia_idx][slot_idx+1])
                                    
                                    #Como es un array natural d python no permite la indexacion de tipo [1,2,3]
                                    self.appointments[server_idx][dia_idx][slot_idx]= test
                                    self.appointments[server_idx][dia_idx][slot_idx+1]=reasign
                                    reasign=[]
                                    
                                if self.patients_list[slot[0]].protected == False:
                                    self.cwt_non_protected += self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.patients_list[slot[0]].waiting_time = self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.non_protected_assistance += 1
                                else:
                                    self.cwt_protected += self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.patients_list[slot[0]].waiting_time = self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.protected_assistance += 1
                            # Ninguno de los overbooked shows up
                            elif not ids:
                                self.idle_time_server[server_idx]+=self.slot_time
                            
                            # Solo uno de los overbooked shows up
                            else:
                                self.appointments[server_idx][dia_idx][slot_idx]=[ids[0]]
                                if self.patients_list[slot[0]].protected == False:
                                    self.cwt_non_protected += self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.patients_list[slot[0]].waiting_time = self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.non_protected_assistance += 1
                                else:
                                    self.cwt_protected += self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.patients_list[slot[0]].waiting_time = self.compute_waiting_time(dia_idx, slot_idx, slot[0])
                                    self.protected_assistance += 1
    
                                #self.service_time[server_idx]+=self.slot_time

    def not_null(self, lista):
        return max(len(lista) - lista.count(None), 0)
    
    def get_measures(self):

        protected_overbooked_patients = 0
        non_protected_overbooked_patients = 0

        protected_overbooked_waiting_time = 0
        non_protected_overbooked_waiting_time = 0

        total_attended_patients = 0
        
        for server in self.appointments:
            for dia in server:
                for slot in dia:
                    for patient_id in slot:
                        if patient_id is None:
                            continue
                        
                        # añadido esto para luego calcular waiting time general
                        if self.patients_list[patient_id].attendance:
                            total_attended_patients += 1

                        if self.patients_list[patient_id].overbooked:
                            if self.patients_list[patient_id].protected and self.patients_list[patient_id].assigned and self.patients_list[patient_id].attendance:
                                protected_overbooked_patients += 1
                                protected_overbooked_waiting_time += self.patients_list[patient_id].waiting_time
                            elif not self.patients_list[patient_id].protected and self.patients_list[patient_id].assigned and self.patients_list[patient_id].attendance:
                                non_protected_overbooked_patients += 1
                                non_protected_overbooked_waiting_time += self.patients_list[patient_id].waiting_time
        
        # for server in self.appointments:
        #     for dia in server: 
        #         for slot in dia:
        #             if len(slot) > 1:
        #                 for patient_id in slot:
        #                     if self.patients_list[patient_id].protected and self.patients_list[patient_id].attendance:
        #                         protected_overbooked_waiting_time += self.patients_list[patient_id].waiting_time
        #                     elif not self.patients_list[patient_id].protected and self.patients_list[patient_id].attendance:
        #                         non_protected_overbooked_waiting_time += self.patients_list[patient_id].waiting_time

        total_waiting_time = self.cwt_protected + self.cwt_non_protected

        measures = {
            "idle_time_server": self.idle_time_server.tolist(),  # NumPy array to list
            "over_time": self.over_time.tolist(), # NumPy array to list
            "no_shows": self.no_shows,
            "clients_total_waiting_time protected class": max(0, self.cwt_protected),
            "clients_total_waiting_time non protected class": max(0,self.cwt_non_protected),
            #"service_time": self.service_time.tolist()  # NumPy array to list
            
            # added this for patient waiting time
            "protected_assistance": self.protected_assistance,
            "non_protected_assistance": self.non_protected_assistance,
            "protected_overbooked_patients": protected_overbooked_patients,
            "non_protected_overbooked_patients": non_protected_overbooked_patients,
            "protected_overbooked_waiting_time": protected_overbooked_waiting_time,
            "non_protected_overbooked_waiting_time": non_protected_overbooked_waiting_time, 

            # added to have also general times
            "total_attended_patients": total_attended_patients,
            "total_waiting_time": total_waiting_time, 
            "patient_waiting_time": total_waiting_time/total_attended_patients
        }
        return measures