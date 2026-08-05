function contract_path = create_generic_vehicle_contract(output_dir, vehicle_kind, motor_count)
%CREATE_GENERIC_VEHICLE_CONTRACT Create a reviewed V3 template contract.
% Supports fixed-wing axis actuators or an N-motor multirotor.  It creates a
% contract only; callers must still pair it with a matching generated model.
    if nargin < 1, output_dir = pwd; end
    if nargin < 2, vehicle_kind = 'multirotor'; end
    if nargin < 3, motor_count = 6; end
    if ~exist(output_dir, 'dir'), mkdir(output_dir); end
    if ~any(strcmp(vehicle_kind, {'multirotor','fixed_wing'}))
        error('vehicle_kind must be multirotor or fixed_wing');
    end
    if ~isscalar(motor_count) || motor_count < 1 || motor_count > 32 || floor(motor_count) ~= motor_count
        error('motor_count must be an integer from 1 to 32');
    end
    if strcmp(vehicle_kind, 'fixed_wing')
        model_name = 'fixed_wing_hil';
    else
        model_name = sprintf('multirotor_%d_hil', motor_count);
    end
    sources = {'demo_mission','px4_sitl','physical_uut'};
    % The repository demo mission computes four rotor commands.  A fixed-wing
    % plant must not reinterpret those as throttle/surface commands.
    if strcmp(vehicle_kind, 'fixed_wing') || motor_count ~= 4
        sources = {'px4_sitl','physical_uut'};
    end
    contract = struct('contract_version', 3, 'model_name', model_name, 'vehicle_kind', vehicle_kind, ...
        'control_sources', {sources}, ...
        'sensors', struct('imu', struct('rate_hz',250), 'gps', struct('rate_hz',20), ...
                          'magnetometer', struct('rate_hz',50), 'barometer', struct('rate_hz',50)));
    contract.state = standard_state();
    if strcmp(vehicle_kind, 'fixed_wing')
        contract.inputs.flight_control = axis_inputs();
        names = {'throttle','roll_cmd','pitch_cmd','yaw_cmd'};
        for i = 1:length(names)
            minimum = -1.0;
            if strcmp(names{i}, 'throttle'), minimum = 0.0; end
            channels(i) = actuator(names{i}, ['flight_control.' names{i}], minimum, 1.0, 0.0); %#ok<AGROW>
        end
    else
        contract.inputs.flight_control = motor_inputs(motor_count);
        for i = 1:motor_count
            channels(i) = actuator(sprintf('motor_%02d', i), 'flight_control.motor_command', 0.0, 1.0, 0.0, i-1); %#ok<AGROW>
        end
    end
    contract.actuators = struct('channels', channels);
    contract.inputs.environment = environment_inputs();
    contract.inputs.fault = fault_inputs();
    contract.outputs.internal_state = internal_outputs();
    contract.execution = struct('step_s',0.001, 'locked_configuration', ...
        {{'solver_step_s','model_topology','port_schema','communication_endpoint'}});
    contract.parameters = generic_parameters(vehicle_kind);
    contract_path = fullfile(output_dir, 'hil_contract.json');
    fid = fopen(contract_path, 'w');
    if fid < 0, error('Cannot write %s', contract_path); end
    fprintf(fid, '%s\n', jsonencode(contract)); fclose(fid);
end

function state = standard_state()
    names = {'north_m','east_m','down_m','vn_mps','ve_mps','vd_mps','q_w','q_x','q_y','q_z','p_radps','q_radps','r_radps','airborne'};
    units = {'m','m','m','m/s','m/s','m/s','1','1','1','1','rad/s','rad/s','rad/s','bool'};
    for i = 1:length(names), state.outputs.(names{i}) = names{i}; state.units.(names{i}) = units{i}; end
    state.frame = 'NED'; state.orientation = 'FRD_TO_NED_QUATERNION';
end
function flight = axis_inputs()
    flight.mode = 'axis_command'; names = {'throttle','roll_cmd','pitch_cmd','yaw_cmd'};
    for i = 1:length(names)
        minimum = -1; if strcmp(names{i}, 'throttle'), minimum = 0; end
        flight.ports.(names{i}) = descriptor(names{i},'1','double',1,minimum,1);
    end
end
function flight = motor_inputs(count)
    flight.mode = 'motor_command'; flight.ports.motor_command = descriptor('motor_command','1','double',count,0,1);
end
function value = environment_inputs()
    fields = {'wind_n_mps','m/s',-50,50,0;'wind_e_mps','m/s',-50,50,0;'wind_d_mps','m/s',-50,50,0; ...
        'pressure_pa','Pa',1000,120000,101325;'temperature_k','K',150,350,288.15;'ground_height_m','m',-1000,10000,0};
    for i = 1:size(fields,1), value.ports.(fields{i,1}) = descriptor(fields{i,1},fields{i,2},'double',1,fields{i,3},fields{i,4},fields{i,5}); end
end
function value = fault_inputs()
    fields = {'gps_bias_n_m','m','double',-1000,1000;'gps_bias_e_m','m','double',-1000,1000;'gps_bias_d_m','m','double',-1000,1000; ...
        'imu_bias_p_radps','rad/s','double',-10,10;'imu_bias_q_radps','rad/s','double',-10,10;'imu_bias_r_radps','rad/s','double',-10,10; ...
        'motor_1_failed','bool','bool',0,1;'motor_2_failed','bool','bool',0,1;'motor_3_failed','bool','bool',0,1;'motor_4_failed','bool','bool',0,1; ...
        'command_delay_ms','ms','double',0,1000;'sensor_delay_ms','ms','double',0,1000;'packet_loss_ratio','1','double',0,1};
    for i = 1:size(fields,1), value.ports.(fields{i,1}) = descriptor(fields{i,1},fields{i,2},fields{i,3},1,fields{i,4},fields{i,5}); end
end
function value = internal_outputs()
    value.rate_hz = 50; value.consumer = 'c_python_only'; value.include_in_ue4_json = false;
    value.acceleration.ax_mps2 = descriptor('ax_mps2','m/s2','double',1,-200,200);
    value.acceleration.ay_mps2 = descriptor('ay_mps2','m/s2','double',1,-200,200);
    value.acceleration.az_mps2 = descriptor('az_mps2','m/s2','double',1,-200,200);
end
function channel = actuator(name, input, minimum, maximum, safe_value, index)
    if nargin < 6, index = 0; end
    channel = struct('name',name,'unit','1','min',minimum,'max',maximum,'safe_value',safe_value, ...
        'binding',struct('input',input,'index',index));
end
function value = descriptor(field, unit, type, dimension, minimum, maximum, default_value)
    value = struct('field',field,'unit',unit,'type',type,'dimension',dimension,'min',minimum,'max',maximum);
    if nargin >= 7, value.default = default_value; end
end
function params = generic_parameters(vehicle_kind)
    names = {'mass_kg','kg',2.0,0.1,100.0;'inertia_xx_kgm2','kg*m2',0.03,0.0001,10.0;'inertia_yy_kgm2','kg*m2',0.03,0.0001,10.0; ...
        'inertia_zz_kgm2','kg*m2',0.05,0.0001,10.0;'linear_drag_ns_m','N*s/m',0.2,0,100.0;'angular_drag_nms','N*m*s',0.02,0,100.0; ...
        'wind_n_bias_mps','m/s',0,-50,50;'wind_e_bias_mps','m/s',0,-50,50;'wind_d_bias_mps','m/s',0,-50,50};
    if strcmp(vehicle_kind,'multirotor'), names(end+1,:) = {'thrust_coefficient_n','N',4.2,0.01,100.0};
    else, names(end+1,:) = {'wing_area_m2','m2',0.25,0.01,20.0}; end
    for i = 1:size(names,1)
        binding = struct('kind','exported_global','symbol',['uav_' names{i,1}]);
        params(i) = struct('name',names{i,1},'generated_field',['uav_' names{i,1}], 'type','double','unit',names{i,2}, ...
            'default',names{i,3},'min',names{i,4},'max',names{i,5},'class','live','allowed_phases',{{'RUNNING','PAUSED'}},'binding',binding); %#ok<AGROW>
    end
end
