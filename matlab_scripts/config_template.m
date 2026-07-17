function config = get_codegen_config(model_name, model_type)
    config = struct();
    config.SystemTargetFile = 'ert.tlc';
    config.TargetLang = 'C';
    config.GenerateComments = 'on';
    config.GenerateReport = 'on';
    config.GenerateCodeOnly = 'on';
    config.SolverType = 'Fixed-step';
    config.Solver = 'FixedStepDiscrete';
    config.FixedStep = '0.001';
    config.ParameterTuning = 'on';

    switch model_type
        case 'quadrotor'
            config.SupportContinuousTime = 'on';
            config.SupportDiscreteTime = 'on';
        case 'fixedwing'
            config.SupportContinuousTime = 'on';
            config.SupportDiscreteTime = 'on';
        otherwise
            config.SupportContinuousTime = 'off';
            config.SupportDiscreteTime = 'on';
    end

    fields = fieldnames(config);
    for i = 1:length(fields)
        try
            set_param(model_name, fields{i}, config.(fields{i}));
        catch
        end
    end
end