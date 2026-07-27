function generate_test_model(output_dir)
%GENERATE_TEST_MODEL Small explicit-contract ERT acceptance model.
% ``gain`` is a root input and drives North position/velocity.  All required
% NED state fields are root outputs with their exact contract names.
    if nargin < 1, output_dir = pwd; end
    if ~exist(output_dir, 'dir'), mkdir(output_dir); end
    mdl = 'hil_test_model';
    try, close_system(mdl, 0); catch, end
    new_system(mdl); open_system(mdl);
    set_param(mdl, 'SolverType', 'Fixed-step');
    set_param(mdl, 'Solver', 'FixedStepDiscrete');
    set_param(mdl, 'FixedStep', '0.001');
    set_param(mdl, 'StopTime', 'inf');

    mass = Simulink.Parameter(5.0);
    mass.CoderInfo.StorageClass = 'ExportedGlobal';
    assignin('base', 'uav_mass_kg', mass);

    add_block('simulink/Sources/In1', [mdl '/gain']);
    set_param([mdl '/gain'], 'Port', '1');
    add_block('simulink/Sources/In1', [mdl '/reset_gain']);
    set_param([mdl '/reset_gain'], 'Port', '2');
    add_block('simulink/Math Operations/Add', [mdl '/total_gain'], 'Inputs', '++');
    add_line(mdl, 'gain/1', 'total_gain/1');
    add_line(mdl, 'reset_gain/1', 'total_gain/2');
    add_block('simulink/Discrete/Discrete-Time Integrator', [mdl '/north_integrator']);
    set_param([mdl '/north_integrator'], 'gainval', '1', 'SampleTime', '0.001');
    add_line(mdl, 'total_gain/1', 'north_integrator/1');

    add_block('simulink/Sources/Constant', [mdl '/force_newton'], 'Value', '20');
    add_block('simulink/Sources/Constant', [mdl '/mass_kg'], 'Value', 'uav_mass_kg');
    add_block('simulink/Math Operations/Divide', [mdl '/force_over_mass']);
    add_line(mdl, 'force_newton/1', 'force_over_mass/1');
    add_line(mdl, 'mass_kg/1', 'force_over_mass/2');

    outputs = {'north_m','east_m','down_m','vn_mps','ve_mps','vd_mps', ...
        'q_w','q_x','q_y','q_z','p_radps','q_radps','r_radps','airborne'};
    for i = 1:length(outputs)
        add_block('simulink/Sinks/Out1', [mdl '/' outputs{i}]);
        set_param([mdl '/' outputs{i}], 'Port', num2str(i));
    end
    add_line(mdl, 'north_integrator/1', 'north_m/1');
    add_line(mdl, 'total_gain/1', 'vn_mps/1');
    add_line(mdl, 'force_over_mass/1', 've_mps/1');

    constants = {'east_m','0'; 'down_m','0'; 'vd_mps','0'; ...
        'q_w','1'; 'q_x','0'; 'q_y','0'; 'q_z','0'; 'p_radps','0'; ...
        'q_radps','0'; 'r_radps','0'};
    for i = 1:size(constants, 1)
        block = ['const_' constants{i,1}];
        add_block('simulink/Sources/Constant', [mdl '/' block], 'Value', constants{i,2});
        add_line(mdl, [block '/1'], [constants{i,1} '/1']);
    end
    add_block('simulink/Sources/Constant', [mdl '/airborne_source'], 'Value', '1');
    add_block('simulink/Logic and Bit Operations/Compare To Constant', [mdl '/airborne_bool'], ...
        'relop', '>', 'const', '0');
    add_line(mdl, 'airborne_source/1', 'airborne_bool/1');
    add_line(mdl, 'airborne_bool/1', 'airborne/1');
    save_system(mdl, fullfile(output_dir, [mdl '.slx']));
    close_system(mdl, 0);
    evalin('base', 'clear uav_mass_kg');
end
