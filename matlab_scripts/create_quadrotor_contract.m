function contract_path = create_quadrotor_contract(output_dir)
%CREATE_QUADROTOR_CONTRACT Write the explicit V2 ABI for quadrotor_hil.
% Acceleration is an internal C/Python signal.  It is deliberately absent
% from any UE4 JSON declaration; the TCP bridge owns protocol projection.
    if nargin < 1, output_dir = pwd; end
    if ~exist(output_dir, 'dir'), mkdir(output_dir); end

    contract = struct();
    contract.contract_version = 2;
    contract.model_name = 'quadrotor_hil';

    contract.state.frame = 'NED';
    contract.state.orientation = 'FRD_TO_NED_QUATERNION';
    state_outputs.north_m = 'north_m';
    state_outputs.east_m = 'east_m';
    state_outputs.down_m = 'down_m';
    state_outputs.vn_mps = 'vn_mps';
    state_outputs.ve_mps = 've_mps';
    state_outputs.vd_mps = 'vd_mps';
    state_outputs.q_w = 'q_w';
    state_outputs.q_x = 'q_x';
    state_outputs.q_y = 'q_y';
    state_outputs.q_z = 'q_z';
    state_outputs.p_radps = 'p_radps';
    state_outputs.q_radps = 'q_radps';
    state_outputs.r_radps = 'r_radps';
    state_outputs.airborne = 'airborne';
    contract.state.outputs = state_outputs;
    contract.state.units = struct('north_m','m','east_m','m','down_m','m', ...
        'vn_mps','m/s','ve_mps','m/s','vd_mps','m/s', ...
        'q_w','1','q_x','1','q_y','1','q_z','1', ...
        'p_radps','rad/s','q_radps','rad/s','r_radps','rad/s', ...
        'airborne','bool');

    flight_control.mode = 'motor_command';
    flight_control.ports.motor_command = descriptor('motor_command', '1', 'double', 4, 0.0, 1.0);
    contract.inputs.flight_control = flight_control;
    environment.ports.wind_n_mps = defaulted_descriptor('wind_n_mps', 'm/s', 'double', 1, -50.0, 50.0, 0.0);
    environment.ports.wind_e_mps = defaulted_descriptor('wind_e_mps', 'm/s', 'double', 1, -50.0, 50.0, 0.0);
    environment.ports.wind_d_mps = defaulted_descriptor('wind_d_mps', 'm/s', 'double', 1, -50.0, 50.0, 0.0);
    environment.ports.pressure_pa = defaulted_descriptor('pressure_pa', 'Pa', 'double', 1, 1000.0, 120000.0, 101325.0);
    environment.ports.temperature_k = defaulted_descriptor('temperature_k', 'K', 'double', 1, 150.0, 350.0, 288.15);
    environment.ports.ground_height_m = defaulted_descriptor('ground_height_m', 'm', 'double', 1, -1000.0, 10000.0, 0.0);
    contract.inputs.environment = environment;
    fault.ports.gps_bias_n_m = descriptor('gps_bias_n_m', 'm', 'double', 1, -1000.0, 1000.0);
    fault.ports.gps_bias_e_m = descriptor('gps_bias_e_m', 'm', 'double', 1, -1000.0, 1000.0);
    fault.ports.gps_bias_d_m = descriptor('gps_bias_d_m', 'm', 'double', 1, -1000.0, 1000.0);
    fault.ports.imu_bias_p_radps = descriptor('imu_bias_p_radps', 'rad/s', 'double', 1, -10.0, 10.0);
    fault.ports.imu_bias_q_radps = descriptor('imu_bias_q_radps', 'rad/s', 'double', 1, -10.0, 10.0);
    fault.ports.imu_bias_r_radps = descriptor('imu_bias_r_radps', 'rad/s', 'double', 1, -10.0, 10.0);
    fault.ports.motor_1_failed = descriptor('motor_1_failed', 'bool', 'bool', 1, 0.0, 1.0);
    fault.ports.motor_2_failed = descriptor('motor_2_failed', 'bool', 'bool', 1, 0.0, 1.0);
    fault.ports.motor_3_failed = descriptor('motor_3_failed', 'bool', 'bool', 1, 0.0, 1.0);
    fault.ports.motor_4_failed = descriptor('motor_4_failed', 'bool', 'bool', 1, 0.0, 1.0);
    fault.ports.command_delay_ms = descriptor('command_delay_ms', 'ms', 'double', 1, 0.0, 1000.0);
    fault.ports.sensor_delay_ms = descriptor('sensor_delay_ms', 'ms', 'double', 1, 0.0, 1000.0);
    fault.ports.packet_loss_ratio = descriptor('packet_loss_ratio', '1', 'double', 1, 0.0, 1.0);
    contract.inputs.fault = fault;

    internal_acceleration.ax_mps2 = descriptor('ax_mps2', 'm/s2', 'double', 1, -200.0, 200.0);
    internal_acceleration.ay_mps2 = descriptor('ay_mps2', 'm/s2', 'double', 1, -200.0, 200.0);
    internal_acceleration.az_mps2 = descriptor('az_mps2', 'm/s2', 'double', 1, -200.0, 200.0);
    contract.outputs.internal_state.rate_hz = 50;
    contract.outputs.internal_state.consumer = 'c_python_only';
    contract.outputs.internal_state.include_in_ue4_json = false;
    contract.outputs.internal_state.acceleration = internal_acceleration;

    contract.execution.step_s = 0.001;
    contract.execution.locked_configuration = {'solver_step_s','model_topology', ...
        'port_schema','communication_endpoint'};

    contract.parameters = [ ...
        parameter('mass_kg', 'uav_mass_kg', 'kg', 1.5, 0.2, 25.0, 'live'), ...
        parameter('inertia_xx_kgm2', 'uav_inertia_xx_kgm2', 'kg*m2', 0.029, 0.001, 2.0, 'live'), ...
        parameter('inertia_yy_kgm2', 'uav_inertia_yy_kgm2', 'kg*m2', 0.029, 0.001, 2.0, 'live'), ...
        parameter('inertia_zz_kgm2', 'uav_inertia_zz_kgm2', 'kg*m2', 0.055, 0.001, 4.0, 'live'), ...
        parameter('thrust_coefficient_n', 'uav_thrust_coefficient_n', 'N', 4.2, 0.5, 20.0, 'live'), ...
        parameter('moment_coefficient_nm', 'uav_moment_coefficient_nm', 'N*m', 0.08, 0.001, 2.0, 'live'), ...
        parameter('linear_drag_ns_m', 'uav_linear_drag_ns_m', 'N*s/m', 0.25, 0.0, 20.0, 'live'), ...
        parameter('angular_drag_nms', 'uav_angular_drag_nms', 'N*m*s', 0.02, 0.0, 5.0, 'live'), ...
        parameter('wind_n_bias_mps', 'uav_wind_n_bias_mps', 'm/s', 0.0, -30.0, 30.0, 'live'), ...
        parameter('wind_e_bias_mps', 'uav_wind_e_bias_mps', 'm/s', 0.0, -30.0, 30.0, 'live'), ...
        parameter('wind_d_bias_mps', 'uav_wind_d_bias_mps', 'm/s', 0.0, -30.0, 30.0, 'live'), ...
        parameter('motor_efficiency', 'uav_motor_efficiency', '1', 1.0, 0.2, 1.2, 'live')];

    contract_path = fullfile(output_dir, 'hil_contract.json');
    fid = fopen(contract_path, 'w');
    if fid < 0, error('Cannot write %s', contract_path); end
    cleanup = onCleanup(@() fclose(fid)); %#ok<NASGU>
    fprintf(fid, '%s\n', jsonencode(contract));
end

function value = descriptor(field, unit, value_type, dimension, minimum, maximum)
    value = struct('field', field, 'unit', unit, 'type', value_type, ...
        'dimension', dimension, 'min', minimum, 'max', maximum);
end

function value = defaulted_descriptor(field, unit, value_type, dimension, minimum, maximum, default_value)
    value = descriptor(field, unit, value_type, dimension, minimum, maximum);
    value.default = default_value;
end

function value = parameter(name, generated_symbol, unit, default_value, minimum, maximum, parameter_class)
    binding = struct('kind', 'exported_global', 'symbol', generated_symbol);
    value = struct('name', name, 'generated_field', generated_symbol, ...
        'type', 'double', 'unit', unit, 'default', default_value, ...
        'min', minimum, 'max', maximum, 'class', parameter_class, ...
        'allowed_phases', {{'RUNNING','PAUSED'}}, 'binding', binding);
end
