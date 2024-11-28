from project_modules.project_imports import *
from project_modules.classes import Patient, Clinic

class Sampling:
    def random_patient_sample(patients, sample_size, protected_pct, simulation_days):
        # Pecentage of protected patients in the sample
        protected_pct = protected_pct

        def asignar_dia(patient_list_sample, num_days):
            # determinar cuantos pacientes por dia
            patients_per_day = len(patient_list_sample) // num_days
        
            # asignar dia de llamada a cada paciente
            for i, patient in enumerate(patient_list_sample):
                patient.day_of_call = i//patients_per_day
                # patient.id=i
                #patient.properties()

            # organizar por dia de llamada
            patient_list_sample.sort(key=lambda x:x.day_of_call)

            return patient_list_sample
        
        protected_true = [patient for patient in patients if patient.protected]
        protected_false = [patient for patient in patients if not patient.protected]

        high_proba_protected = [patient for patient in protected_true if patient.proba > 0.5]
        high_proba_non_protected = [patient for patient in protected_false if patient.proba > 0.5]

        assert type(high_proba_protected[0]) == Patient, "High proba protected patients in list must be Patient object"
        assert type(high_proba_non_protected[0]) == Patient, "High proba non protected patients in list must be Patient object"

        # Calculate sample sizes for each group 
        total_sample_size = sample_size
        sample_size_protected_true = int(total_sample_size * protected_pct)
        sample_size_protected_false = total_sample_size - sample_size_protected_true

        assert type(sample_size_protected_true) == int, "Protected sample size must be an integer"
        assert type(sample_size_protected_false) == int, "Non Protected sample size must be an integer"

        sample_protected_true = []
        sample_protected_false = []

        # Random selection with high probabilities in sample
        for i in range(sample_size_protected_true):
            # random_patient = protected_true[np.random.choice(len(protected_true))]
            # sample_protected_true.append(random_patient)

            # region muestrear pacientes con alta probabilidad
            if i%3 == 0:
                high_proba_protected_patient = high_proba_protected[np.random.choice(len(high_proba_protected))]
                sample_protected_true.append(high_proba_protected_patient)
            else:
                random_patient = protected_true[np.random.choice(len(protected_true))]
                sample_protected_true.append(random_patient)
            # endregion

        for i in range(sample_size_protected_false):
                # random_patient = protected_false[np.random.choice(len(protected_false))]
                # sample_protected_false.append(random_patient)
                
                # region Comentario para seleccionar pacientes con alta probabilidad
                if i%100_000 == 0:
                    sample_protected_false.append(high_proba_non_protected[np.random.choice(len(high_proba_non_protected))])
                else:
                    sample_protected_false.append(protected_false[np.random.choice(len(protected_false))])
                # endregion
                
        # sample_protected_true = [protected_true[i] for i in np.random.choice(len(protected_true), sample_size_protected_true, replace=False)]
        # sample_protected_false = [protected_false[i] for i in np.random.choice(len(protected_false), sample_size_protected_false, replace=False)]

        # Final stratified sample
        stratified_sample = sample_protected_true + sample_protected_false

        # shuffle final sample
        np.random.shuffle(stratified_sample)

        stratified_sample = asignar_dia(stratified_sample, simulation_days)

        orden_esperado = list(np.arange(0,sample_size,1)) 
        ids_list = list([patient.id for patient in stratified_sample])

        if ids_list != orden_esperado:
            # identificar los que estan en orden diferente
            for i in range(len(ids_list)):
                if ids_list[i] != orden_esperado[i]:
                    stratified_sample[i].id = orden_esperado[i]
                
        return stratified_sample
random_patient_sample = Sampling.random_patient_sample

class Plotting:
    @staticmethod
    def plot_line_graph(y_values, label, ylabel, title):
        plt.figure(figsize=(10, 6))
        plt.title(title, fontsize=18, fontweight='bold')

        plt.plot(y_values, label=label, marker='o', markersize=4, linewidth=1.5, color="navy")
        
        plt.xlabel("Simulation Replica", fontsize=18)
        plt.ylabel(ylabel, fontsize=18)
        
        plt.xticks(np.arange(0, len(y_values), 1), [" " for i in range(1, len(y_values)+1)])
        plt.ylim()

        # plt.legend()
        plt.grid(alpha=0.3)
plot_line_graph = Plotting.plot_line_graph

class Appointments:
    def create_appointments(num_serves, scheduling_days, num_hours_byday, slot_time):
        appointments = []
        num_slots_byday = int(num_hours_byday * (60/slot_time))
        for _ in range(num_serves):
            server = [] 
            for _ in range(scheduling_days):
                dia = []
                for _ in range(num_slots_byday):
                    slot = [None]
                    dia.append(slot) 
                server.append(dia)
            appointments.append(server)
        return appointments
    
    def stablish_attendance(patients_data, 
                        protected_ppv, non_protected_ppv, 
                        protected_npv, non_protected_npv,
                        protected_threshold, non_protected_threshold,
                        benchmark=None):
    
        for patient in patients_data:
            threshold = protected_threshold if patient.protected else non_protected_threshold
            ppv = protected_ppv if patient.protected else non_protected_ppv
            npv = protected_npv if patient.protected else non_protected_npv

            # predice no show
            if patient.proba > threshold:
                patient.attendance = random.random() > ppv
            # predice show
            else:
                patient.attendance = random.random() <= npv
        
        return patients_data
stablish_attendance = Appointments.stablish_attendance
create_appointments = Appointments.create_appointments

class Processing:
    def get_margin_errors(data_list, confidence=0.95):
        # Extract a list of measure names (assuming consistent keys across dictionaries)
        measure_names = list(data_list[0].keys())
        results = {}  # Dictionary to store results

        # Check if all dictionaries have the same set of measures
        for data_dict in data_list:
            if set(data_dict.keys()) != set(measure_names):
                raise ValueError("Dictionaries in the list must have the same set of measures.")
        margin_errors = []
        for measure_name in measure_names:
            # Check if measure is a list
            is_list_measure = isinstance(data_list[0][measure_name], list)

            if is_list_measure:
                # Combine all values into a single list
                measure_values = [val for data_dict in data_list for val in data_dict[measure_name]]
            else:
                # Extract measure values from each dictionary (single value case)
                measure_values = [data_dict[measure_name] for data_dict in data_list]

            # Calculate the margin of error
            mean, margin_of_error = Processing.confidence_interval(measure_values, confidence=confidence)

            # Append margin of error to the list
            margin_errors.append(margin_of_error)
            
            results[measure_name] = {'mean': mean, 'margin_of_error': margin_of_error}

        return results

    def check_convergence_mean(data, converge_mean=0.07, verbose=False):
        results = {}
        results = Processing.get_margin_errors(data)
        
        medidas_converge=['COlumna1','Columna2']

        for key in results:
            margin_error = results[key]['margin_of_error']
            mean = results[key]['mean']
            diff = margin_error/mean
            
            if verbose:
                    print(f"Margin difference with the mean {diff:.4f}")
            
            if diff <= converge_mean:
                converge=True
            else:
                return False, diff
        
        return converge, diff

    def confidence_interval(data, confidence=0.95):
        """ This function calculates the confidence interval for a given set of data.
        Args: data: A list of numerical values (or a single numerical value wrapped in a list).
                confidence: The desired confidence level (default: 0.95).

        Returns: A tuple containing the mean and the margin of error.
        """
        if len(data) == 1:
            data = data[0]  # Extract the single value if only one element

        n = len(data)
        m = np.mean(data)
        std_err = np.std(data, ddof=1) / np.sqrt(n)
        t_value = stats.t.ppf((1 + confidence) / 2, n - 1)
        margin_of_error = t_value * std_err
        return m, margin_of_error

    def calculate_summary(measures_df):
        """
        This function calculates the summary statistics for a given DataFrame of measures.
        Args:
            measures_df: A DataFrame containing the measures to be summarized.
        Returns:
            A DataFrame containing the summary statistics for each column in the input DataFrame."""
        summary = []
        for col in measures_df.columns:
            if isinstance(measures_df[col].iloc[0], list):  # Check if the column contains lists
                values = np.concatenate(measures_df[col].values)
                mean, margin_of_error = Processing.confidence_interval(values)
                summary.append({
                    "column": col,
                    "mean": mean,
                    "confidence_interval": (mean - margin_of_error, mean + margin_of_error),
                    "maximum": np.max(values),
                    "minimum": np.min(values)
                })
            else:
                mean, margin_of_error = Processing.confidence_interval(measures_df[col])
                summary.append({
                    "column": col,
                    "mean": mean,
                    "confidence_interval": (mean - margin_of_error, mean + margin_of_error),
                    "maximum": measures_df[col].max(),
                    "minimum": measures_df[col].min()
                })

        summary_measures_df = pd.DataFrame(summary)
        return summary_measures_df
get_margin_errors = Processing.get_margin_errors
check_convergence_mean = Processing.check_convergence_mean
confidence_interval = Processing.confidence_interval
calculate_summary = Processing.calculate_summary