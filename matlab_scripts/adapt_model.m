function result = adapt_model(slx_path, interface_json_path, output_slx_path)
%ADAPT_MODEL Validate the HIL root-port contract without changing model topology.
%   The HIL runtime can safely bind only scalar numeric root ports.  This
%   function maps well-known aliases and rejects models without position XYZ.

    if nargin < 3
        [folder, name, ~] = fileparts(slx_path);
        output_slx_path = fullfile(folder, [name '_adapted.slx']);
    end
    if nargin < 2
        [folder, name, ~] = fileparts(slx_path);
        interface_json_path = fullfile(folder, [name '_interface.json']);
    end

    fid = fopen(interface_json_path, 'r');
    if fid < 0
        error('Cannot read interface JSON: %s', interface_json_path);
    end
    info = jsondecode(fread(fid, '*char')');
    fclose(fid);

    input_aliases = make_input_aliases();
    output_aliases = make_output_aliases();
    input_mapping = map_ports(info.root_inports, input_aliases);
    output_mapping = map_ports(info.root_outports, output_aliases);

    required_outputs = {'pos_x', 'pos_y', 'pos_z'};
    missing_required = {};
    for i = 1:length(required_outputs)
        key = required_outputs{i};
        if ~isfield(output_mapping, key) || strcmp(output_mapping.(key), 'NOT_FOUND')
            missing_required{end+1} = key;
        end
    end
    if ~isempty(missing_required)
        error('HIL contract violation: required scalar outputs missing: %s', ...
            strjoin(missing_required, ', '));
    end

    % Keep the source model unchanged.  Scope/Constant inference cannot be
    % made reliable for arbitrary uploaded models.
    copyfile(slx_path, output_slx_path);

    result = struct();
    result.adapted = false;
    result.field_mapping = struct();
    result.field_mapping.inputs = input_mapping;
    result.field_mapping.outputs = output_mapping;
    result.field_mapping.model_name = info.model_name;
    result.field_mapping.adapted = false;
    result.field_mapping.required_outputs = required_outputs;
    result.field_mapping.optional_outputs = optional_output_names();
    result.field_mapping.source_slx = slx_path;
    result.warnings = {};

    [folder, ~, ~] = fileparts(output_slx_path);
    mapping_path = fullfile(folder, 'field_mapping.json');
    fid = fopen(mapping_path, 'w');
    if fid < 0
        error('Cannot write field mapping: %s', mapping_path);
    end
    fprintf(fid, '%s', jsonencode(result.field_mapping));
    fclose(fid);

    fprintf('[adapt_model] Contract accepted: %s\n', info.model_name);
    fprintf('[adapt_model] Mapping: %s\n', mapping_path);
end

function aliases = make_input_aliases()
    aliases = containers.Map();
    aliases('cmd_x') = {'cmd_x', 'X_des', 'x_des', 'x_desired', 'ref_x', 'X desired'};
    aliases('cmd_y') = {'cmd_y', 'Y_des', 'y_des', 'y_desired', 'ref_y', 'Y desired'};
    aliases('cmd_z') = {'cmd_z', 'Z_des', 'z_des', 'z_desired', 'ref_z', 'Z desired', 'height_cmd'};
    aliases('cmd_yaw') = {'cmd_yaw', 'Psi_des', 'psi_des', 'yaw_des', 'psi_desired', 'ref_yaw'};
    aliases('cmd_mode') = {'cmd_mode', 'mode', 'flight_mode'};
    aliases('cmd_speed') = {'cmd_speed', 'speed', 'target_speed', 'V_des'};
    aliases('cmd_duration') = {'cmd_duration', 'duration'};
    aliases('lat_init') = {'lat_init', 'initial_lat'};
    aliases('lon_init') = {'lon_init', 'initial_lon'};
    aliases('alt_init') = {'alt_init', 'initial_alt'};
    aliases('roll_init') = {'roll_init', 'initial_roll'};
    aliases('pitch_init') = {'pitch_init', 'initial_pitch'};
    aliases('yaw_init') = {'yaw_init', 'initial_yaw'};
    aliases('init_x') = {'init_x', 'initial_x'};
    aliases('init_y') = {'init_y', 'initial_y'};
    aliases('min_speed') = {'min_speed'};
    aliases('max_speed') = {'max_speed'};
    aliases('min_height') = {'min_height'};
    aliases('max_height') = {'max_height'};
end

function aliases = make_output_aliases()
    aliases = containers.Map();
    aliases('pos_x') = {'pos_x', 'X', 'x', 'x_global', 'x_body'};
    aliases('pos_y') = {'pos_y', 'Y', 'y', 'y_global', 'y_body'};
    aliases('pos_z') = {'pos_z', 'Z', 'z', 'z_global', 'z_body', 'height', 'alt'};
    aliases('roll') = {'roll', 'Phi', 'phi', 'roll_rad'};
    aliases('pitch') = {'pitch', 'Theta', 'theta', 'pitch_rad'};
    aliases('yaw') = {'yaw', 'Psi', 'psi', 'yaw_rad'};
    aliases('vel_x') = {'vel_x', 'vx', 'x_dot', 'Vx', 'v_x'};
    aliases('vel_y') = {'vel_y', 'vy', 'y_dot', 'Vy', 'v_y'};
    aliases('vel_z') = {'vel_z', 'vz', 'z_dot', 'Vz', 'v_z'};
    aliases('acc_x') = {'acc_x', 'ax', 'x_ddot'};
    aliases('acc_y') = {'acc_y', 'ay', 'y_ddot'};
    aliases('acc_z') = {'acc_z', 'az', 'z_ddot'};
    aliases('lat') = {'lat', 'latitude'};
    aliases('lon') = {'lon', 'longitude'};
    aliases('alt') = {'altitude', 'gps_altitude'};
    aliases('airborne') = {'airborne', 'is_airborne', 'in_air'};
end

function mapping = map_ports(ports, aliases)
    mapping = struct();
    keys_list = keys(aliases);
    for i = 1:length(keys_list)
        key = keys_list{i};
        mapping.(key) = 'NOT_FOUND';
        candidates = aliases(key);
        for p = 1:length(ports)
            port = get_port(ports, p);
            port_name = strtrim(port.name);
            for c = 1:length(candidates)
                if strcmpi(port_name, candidates{c})
                    mapping.(key) = port.name;
                    break;
                end
            end
            if ~strcmp(mapping.(key), 'NOT_FOUND')
                break;
            end
        end
    end
end

function port = get_port(ports, index)
%JSONDECODE returns a structure array for uniform JSON object arrays.
%Keep cell indexing too, so manually-produced heterogeneous data still works.
    if iscell(ports)
        port = ports{index};
    else
        port = ports(index);
    end
end

function names = optional_output_names()
    names = {'roll', 'pitch', 'yaw', 'vel_x', 'vel_y', 'vel_z', ...
             'acc_x', 'acc_y', 'acc_z', 'lat', 'lon', 'alt', 'airborne'};
end
