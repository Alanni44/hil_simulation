function result = adapt_model(slx_path, interface_json_path, output_slx_path)
%ADAPT_MODEL 程序化适配 .slx 模型接口，使其兼容 HIL 系统
%   result = adapt_model(SLX_PATH, INTERFACE_JSON, OUTPUT_SLX)
%
% 适配策略:
%   Level 1: 模型已有 Inport/Outport → 仅生成 field_mapping.json (不改 .slx)
%   Level 2: 模型无标准接口       → 程序化注入 Inport/Outport
%
% 输入:
%   slx_path            - 原始 .slx 文件路径
%   interface_json_path - analyze_model.m 输出的 JSON 路径
%   output_slx_path     - 适配后的 .slx 保存路径 (如无需改动则复制原文件)
%
% 输出结构体:
%   adapted       - 是否做了 .slx 修改
%   field_mapping - 字段映射表
%   warnings      - 警告信息

    if nargin < 3
        [p, n, ~] = fileparts(slx_path);
        output_slx_path = fullfile(p, [n '_adapted.slx']);
    end
    if nargin < 2
        [p, n, ~] = fileparts(slx_path);
        interface_json_path = fullfile(p, [n '_interface.json']);
    end

    % ---- Read interface analysis ----
    fid = fopen(interface_json_path, 'r');
    if fid < 0
        error('Cannot read interface JSON: %s', interface_json_path);
    end
    raw = fread(fid, '*char')';
    fclose(fid);
    info = jsondecode(raw);

    % ---- Standard HIL field name aliases ----
    input_aliases = containers.Map();
    input_aliases('cmd_x')   = {'cmd_x','X_des','x_des','x_desired','ref_x','X desired'};
    input_aliases('cmd_y')   = {'cmd_y','Y_des','y_des','y_desired','ref_y','Y desired'};
    input_aliases('cmd_z')   = {'cmd_z','Z_des','z_des','z_desired','ref_z','Z desired','height_cmd'};
    input_aliases('cmd_yaw') = {'cmd_yaw','Psi_des','psi_des','yaw_des','psi_desired','ref_yaw'};
    input_aliases('cmd_mode') = {'cmd_mode','mode','flight_mode'};
    input_aliases('cmd_speed') = {'cmd_speed','speed','target_speed','V_des'};

    output_aliases = containers.Map();
    output_aliases('pos_x') = {'pos_x','X','x','x_global','x_body'};
    output_aliases('pos_y') = {'pos_y','Y','y','y_global','y_body'};
    output_aliases('pos_z') = {'pos_z','Z','z','z_global','z_body','height','alt'};
    output_aliases('roll')  = {'roll','Phi','phi','roll_rad'};
    output_aliases('pitch') = {'pitch','Theta','theta','pitch_rad'};
    output_aliases('yaw')   = {'yaw','Psi','psi','yaw_rad'};
    output_aliases('vel_x') = {'vel_x','vx','x_dot','Vx','v_x'};
    output_aliases('vel_y') = {'vel_y','vy','y_dot','Vy','v_y'};
    output_aliases('vel_z') = {'vel_z','vz','z_dot','Vz','v_z'};

    result = struct();
    result.adapted = false;
    result.field_mapping = struct();
    result.warnings = {};

    % ---- Build matching tables ----
    function mapping = match_fields(standard_keys, aliases_map, model_ports)
        mapping = struct();
        keys_list = keys(aliases_map);
        for i = 1:length(keys_list)
            std_key = keys_list{i};
            candidates = aliases_map(std_key);
            matched = false;
            for c = 1:length(candidates)
                for p = 1:length(model_ports)
                    % Normalize: strip newlines/spaces for comparison
                    port_name = strrep(model_ports{p}.name, sprintf('\n'), ' ');
                    candidate = candidates{c};
                    if strcmpi(strtrim(port_name), strtrim(candidate))
                        mapping.(std_key) = model_ports{p}.name;
                        matched = true;
                        break;
                    end
                end
                if matched, break; end
            end
            if ~matched
                mapping.(std_key) = 'NOT_FOUND';
            end
        end
    end

    input_mapping = match_fields(keys(input_aliases), input_aliases, info.root_inports);
    output_mapping = match_fields(keys(output_aliases), output_aliases, info.root_outports);

    missing_inputs = {};
    missing_outputs = {};
    std_inputs = keys(input_aliases);
    std_outputs = keys(output_aliases);
    for i = 1:length(std_inputs)
        if strcmp(input_mapping(std_inputs{i}), 'NOT_FOUND')
            missing_inputs{end+1} = std_inputs{i};
        end
    end
    for i = 1:length(std_outputs)
        if strcmp(output_mapping(std_outputs{i}), 'NOT_FOUND')
            missing_outputs{end+1} = std_outputs{i};
        end
    end

    % ---- Level 1: model already has matching ports → no SLX modification ----
    has_standard_ports = ~isempty(missing_inputs) || ~isempty(missing_outputs);
    % Quad_sim has no Inports/Outports at all AND is continuous → always needs Level 2
    needs_level2 = info.needs_adaptation || has_standard_ports;

    if ~needs_level2
        fprintf('[adapt_model] Model has complete standard interface, no adaptation needed\n');
        copyfile(slx_path, output_slx_path);
        result.field_mapping.inputs = input_mapping;
        result.field_mapping.outputs = output_mapping;
        result.field_mapping.model_name = info.model_name;
        result.field_mapping.adapted = false;

        % Write field_mapping.json alongside output
        [p, ~, ~] = fileparts(output_slx_path);
        mapping_path = fullfile(p, 'field_mapping.json');
        fid = fopen(mapping_path, 'w');
        fprintf(fid, '%s', jsonencode(result.field_mapping));
        fclose(fid);
        return;
    end

    % ---- Level 2: needs programmatic adaptation ----
    fprintf('[adapt_model] Model needs adaptation:\n');
    if ~isempty(missing_inputs)
        fprintf('  Missing inputs: %s\n', strjoin(missing_inputs, ', '));
    end
    if ~isempty(missing_outputs)
        fprintf('  Missing outputs: %s\n', strjoin(missing_outputs, ', '));
    end
    if info.is_continuous
        fprintf('  Continuous solver detected, will switch to Fixed-step in build\n');
    end

    model_name = info.model_name;
    load_system(slx_path);

    new_model = [model_name '_adapted'];
    % If the adapted model is already open, close it first
    try
        bdclose(new_model);
    catch
    end

    % Save a copy as the adapted model
    save_system(model_name, output_slx_path);
    bdclose(model_name);

    % Re-open the copy for modification
    load_system(output_slx_path);
    [~, new_name, ~] = fileparts(output_slx_path);

    % ---- 2a: Convert ALL root Constant/Step blocks to Inports ----
    % ALL constants become Inports so they are tunable at runtime via UDP JSON.
    % Blocks with a standard alias (e.g. X_des -> cmd_x) get the standard name;
    % blocks without (e.g. m, g, Kdx/m) keep their original name as Inport.
    source_blocks = [info.root_constants, info.root_steps];
    std_keys_cell = keys(input_aliases);
    if ~isempty(std_keys_cell)
        standard_std_keys = std_keys_cell(:)';  % ensure row cell array
    else
        standard_std_keys = {};
    end
    inport_counter = length(info.root_inports) + 1;
    all_tunable = struct();  % track every tunable param

    for s = 1:length(source_blocks)
        src_name = source_blocks{s};
        src_path = [new_name '/' src_name];

        % Find which standard key this source maps to (may stay empty)
        mapped_key = '';
        for i = 1:length(standard_std_keys)
            candidates = input_aliases(standard_std_keys{i});
            for c = 1:length(candidates)
                if strcmpi(strtrim(src_name), strtrim(candidates{c}))
                    mapped_key = standard_std_keys{i};
                    break;
                end
            end
            if ~isempty(mapped_key), break; end
        end

        try
            % Get original Constant value for tunable param record
            orig_value = [];
            try
                orig_value = get_param(src_path, 'Value');
                if ~isempty(orig_value)
                    orig_value = strtrim(orig_value);
                end
            catch
            end

            % Get the block's output connections
            pc = get_param(src_path, 'PortConnectivity');
            dst_info = [];
            for p_idx = 1:length(pc)
                if ~isempty(pc(p_idx).DstBlock)
                    for d = 1:length(pc(p_idx).DstBlock)
                        dst_info = [dst_info; struct( ...
                            'block', pc(p_idx).DstBlock(d), ...
                            'port', pc(p_idx).DstPort(d) + 1)];
                    end
                end
            end

            % Use standard key name if available, otherwise keep original
            if ~isempty(mapped_key)
                inport_name = mapped_key;
            else
                inport_name = src_name;  % keep original name (m, g, Kd, etc.)
            end

            safe_name = matlab.lang.makeValidName(inport_name);
            inport_path = [new_name '/' safe_name];

            % Delete old Constant/Step
            delete_block(src_path);

            % Add Inport
            add_block('simulink/Sources/In1', inport_path);
            set_param(inport_path, 'Port', num2str(inport_counter));
            inport_counter = inport_counter + 1;

            % Rewire to downstream blocks
            for d = 1:size(dst_info, 1)
                dst_block_name = get_param(dst_info(d).block, 'Name');
                dst_port_str = num2str(dst_info(d).port);
                try
                    add_line(new_name, [safe_name '/1'], ...
                        [dst_block_name '/' dst_port_str], 'autorouting', 'on');
                catch
                    result.warnings{end+1} = sprintf(...
                        'Cannot wire %s -> %s/%s', ...
                        safe_name, dst_block_name, dst_port_str);
                end
            end

            % Update mapping (even for non-standard names)
            if ~isempty(mapped_key)
                input_mapping.(mapped_key) = safe_name;
            end

            % Record as tunable
            all_tunable.(safe_name) = struct(...
                'original_block', src_name, ...
                'original_value', orig_value, ...
                'standard_name', mapped_key);

            fprintf('  [inport] %s -> %s (standard=%s, value=%s)\n', ...
                src_name, safe_name, mapped_key, ...
                string(orig_value));

        catch ME
            result.warnings{end+1} = sprintf('Failed to adapt "%s": %s', src_name, ME.message);
        end
    end

    % ---- 2b: Tap Scope/ToWorkspace signals → Outports ----
    sink_blocks = [info.root_scopes, info.root_to_workspace];
    outport_counter = length(info.root_outports) + 1;

    for s = 1:length(sink_blocks)
        snk_name = sink_blocks{s};
        snk_path = [new_name '/' snk_name];

        % Find which standard key this sink maps to
        mapped_key = '';
        for i = 1:length(standard_std_keys)
            candidates = output_aliases(standard_std_keys{i});
            for c = 1:length(candidates)
                if strcmpi(strtrim(snk_name), strtrim(candidates{c}))
                    mapped_key = standard_std_keys{i};
                    break;
                end
            end
            if ~isempty(mapped_key), break; end
        end

        try
            pc = get_param(snk_path, 'PortConnectivity');
            if isempty(pc) || isempty(pc(1).SrcBlock)
                continue;
            end
            src_block_handle = pc(1).SrcBlock;
            src_block_name = get_param(src_block_handle, 'Name');
            src_port = pc(1).SrcPort + 1;

            outport_name = snk_name;
            if ~isempty(mapped_key)
                outport_name = mapped_key;
            end
            safe_name = matlab.lang.makeValidName(outport_name);
            outport_path = [new_name '/' safe_name];

            add_block('simulink/Sinks/Out1', outport_path);
            set_param(outport_path, 'Port', num2str(outport_counter));
            outport_counter = outport_counter + 1;

            add_line(new_name, [src_block_name '/' num2str(src_port)], ...
                [safe_name '/1'], 'autorouting', 'on');

            if ~isempty(mapped_key)
                output_mapping.(mapped_key) = safe_name;
            end
            fprintf('  [outport] %s -> %s (from %s/%d)\n', ...
                snk_name, safe_name, src_block_name, src_port);
        catch ME
            result.warnings{end+1} = sprintf('Failed to tap "%s": %s', snk_name, ME.message);
        end
    end

    % ---- Save adapted model ----
    save_system(new_name);
    bdclose(new_name);

    % ---- Write field_mapping.json ----
    [p, ~, ~] = fileparts(output_slx_path);
    mapping_path = fullfile(p, 'field_mapping.json');

    result.field_mapping.inputs = input_mapping;
    result.field_mapping.outputs = output_mapping;
    result.field_mapping.model_name = new_name;
    result.field_mapping.adapted = true;
    result.field_mapping.source_slx = slx_path;
    % Include tunable params (ALL converted constants, not just standard-named)
    if exist('all_tunable', 'var')
        result.field_mapping.tunable_params = all_tunable;
    else
        result.field_mapping.tunable_params = struct();
    end

    fid = fopen(mapping_path, 'w');
    fprintf(fid, '%s', jsonencode(result.field_mapping));
    fclose(fid);

    fprintf('\n[adapt_model] Done. Adapted model: %s\n', output_slx_path);
    fprintf('[adapt_model] Field mapping: %s\n', mapping_path);
    if ~isempty(result.warnings)
        fprintf('[adapt_model] Warnings:\n');
        for w = 1:length(result.warnings)
            fprintf('  - %s\n', result.warnings{w});
        end
    end
end
