function analyze_model(slx_path, output_json_path)
%ANALYZE_MODEL 分析 .slx 模型的接口结构，输出 JSON
%   analyze_model(SLX_PATH, OUTPUT_JSON_PATH)
%
% 输入:
%   slx_path          - .slx 文件路径
%   output_json_path  - 输出 JSON 文件路径
%
% 输出 JSON 字段:
%   model_name        - 模型名称
%   solver / solver_type / fixed_step / system_target
%   root_inports      - 根级 Inport 列表 [{name, port, type, dimension}]
%   root_outports     - 根级 Outport 列表 [{name, port, type, dimension}]
%   candidate_parameters - 可导出的候选参数（仅供人工审核）
%   unresolved_items  - 无法自动确认物理语义的端口/参数
%   root_constants    - 根级 Constant 块名称列表
%   root_steps        - 根级 Step 块名称列表
%   root_scopes       - 根级 Scope 块名称列表
%   root_to_workspace - 根级 ToWorkspace 块名称列表
%   root_subsystems   - 根级 SubSystem 名称列表
%   integrator_count  - 模型中 Integrator 总数
%   needs_adaptation  - 是否需要适配 (无 Inport/Outport 或连续求解器)
%   is_continuous     - 是否使用连续求解器

    [~, model_name, ~] = fileparts(slx_path);

    fprintf('[analyze_model] Loading: %s\n', slx_path);
    load_system(slx_path);

    info = struct();
    info.model_name = model_name;
    info.slx_path = slx_path;

    % ---- Solver config ----
    try
        info.solver = get_param(model_name, 'Solver');
    catch
        info.solver = '';
    end
    try
        info.solver_type = get_param(model_name, 'SolverType');
    catch
        info.solver_type = '';
    end
    try
        info.fixed_step = get_param(model_name, 'FixedStep');
    catch
        info.fixed_step = '';
    end
    try
        info.system_target = get_param(model_name, 'SystemTargetFile');
    catch
        info.system_target = '';
    end
    try
        info.stop_time = get_param(model_name, 'StopTime');
    catch
        info.stop_time = '';
    end
    try
        info.target_lang = get_param(model_name, 'TargetLang');
    catch
        info.target_lang = '';
    end

    % Compile once to obtain declared root-port data types and dimensions.
    % Any failure is recorded in the draft rather than guessed.
    compiled_available = false;
    try
        set_param(model_name, 'SimulationCommand', 'update');
        compiled_available = true;
    catch ME
        info.compile_warning = ME.message;
    end

    % ---- Root-level Inports ----
    inports = find_system(model_name, 'SearchDepth', 1, 'BlockType', 'Inport');
    info.root_inports = {};
    for i = 1:length(inports)
        name = get_param(inports{i}, 'Name');
        port_str = get_param(inports{i}, 'Port');
        port_num = str2double(port_str);
        descriptor = struct('name', name, 'port', port_num, 'type', '', 'dimension', 0);
        if compiled_available
            try
                descriptor.type = get_param(inports{i}, 'CompiledPortDataTypes');
                descriptor.type = descriptor.type.Outport{1};
                dimensions = get_param(inports{i}, 'CompiledPortWidths');
                descriptor.dimension = dimensions.Outport(1);
            catch
            end
        end
        info.root_inports{end+1} = descriptor;
    end

    % ---- Root-level Outports ----
    outports = find_system(model_name, 'SearchDepth', 1, 'BlockType', 'Outport');
    info.root_outports = {};
    for i = 1:length(outports)
        name = get_param(outports{i}, 'Name');
        port_str = get_param(outports{i}, 'Port');
        port_num = str2double(port_str);
        descriptor = struct('name', name, 'port', port_num, 'type', '', 'dimension', 0);
        if compiled_available
            try
                descriptor.type = get_param(outports{i}, 'CompiledPortDataTypes');
                descriptor.type = descriptor.type.Inport{1};
                dimensions = get_param(outports{i}, 'CompiledPortWidths');
                descriptor.dimension = dimensions.Inport(1);
            catch
            end
        end
        info.root_outports{end+1} = descriptor;
    end

    % ---- Root-level source/sink blocks ----
    function names = get_block_names(sys, blk_type)
        blks = find_system(sys, 'SearchDepth', 1, 'BlockType', blk_type);
        names = {};
        for j = 1:length(blks)
            names{end+1} = get_param(blks{j}, 'Name');
        end
    end

    info.root_constants = get_block_names(model_name, 'Constant');
    info.root_steps = get_block_names(model_name, 'Step');
    info.root_scopes = get_block_names(model_name, 'Scope');
    info.root_to_workspace = get_block_names(model_name, 'ToWorkspace');
    info.root_subsystems = get_block_names(model_name, 'SubSystem');
    info.root_references = get_block_names(model_name, 'Reference');

    % ---- Integrator count (total, any depth) ----
    integrators = find_system(model_name, 'BlockType', 'Integrator');
    info.integrator_count = length(integrators);

    % ---- Continuous? ----
    info.is_continuous = ~strcmp(info.solver_type, 'Fixed-step');

    % ---- Needs adaptation? ----
    has_io_interface = ~isempty(info.root_inports) || ~isempty(info.root_outports);
    info.needs_adaptation = (~has_io_interface) || info.is_continuous;

    % A draft is intentionally descriptive only.  It identifies conventional
    % names as candidates but never supplies units, frames, ranges, actuator
    % semantics or parameter permissions on behalf of an operator.
    info.candidate_state_fields = standard_name_candidates(info.root_outports, ...
        {'north_m','east_m','down_m','vn_mps','ve_mps','vd_mps', ...
         'q_w','q_x','q_y','q_z','p_radps','q_radps','r_radps','airborne'});
    info.candidate_input_fields = standard_name_candidates(info.root_inports, ...
        {'motor_command','throttle','roll_cmd','pitch_cmd','yaw_cmd', ...
         'wind_n_mps','wind_e_mps','wind_d_mps','pressure_pa','temperature_k','ground_height_m'});
    info.candidate_parameters = candidate_tunable_parameters(model_name);
    info.unresolved_items = unresolved_items(info.root_inports, info.root_outports, ...
        info.candidate_state_fields, info.candidate_input_fields, info.candidate_parameters);

    % ---- Write JSON ----
    fid = fopen(output_json_path, 'w');
    if fid < 0
        error('Cannot write to: %s', output_json_path);
    end
    fprintf(fid, '%s', jsonencode(info));
    fclose(fid);
    write_contract_draft(output_json_path, info);

    % ---- Summary ----
    fprintf('\n========== [analyze_model] %s ==========\n', model_name);
    fprintf('  Solver:       %s / %s / step=%s\n', ...
        info.solver_type, info.solver, info.fixed_step);
    fprintf('  Target:       %s (%s)\n', info.system_target, info.target_lang);
    fprintf('  StopTime:     %s\n', info.stop_time);
    fprintf('  Continuous:   %d  (integ=%d)\n', ...
        info.is_continuous, info.integrator_count);
    fprintf('  Root Inports: %d  Outports: %d\n', ...
        length(info.root_inports), length(info.root_outports));
    fprintf('  Constants: %d  Steps: %d  Scopes: %d  ToWorkspace: %d\n', ...
        length(info.root_constants), length(info.root_steps), ...
        length(info.root_scopes), length(info.root_to_workspace));
    fprintf('  SubSystems: %d  References: %d\n', ...
        length(info.root_subsystems), length(info.root_references));

    if info.needs_adaptation
        reasons = {};
        if ~has_io_interface
            reasons{end+1} = 'no root Inport/Outport';
        end
        if info.is_continuous
            reasons{end+1} = sprintf('continuous solver (%s)', info.solver);
        end
        fprintf('  -> NEEDS ADAPTATION: %s\n', strjoin(reasons, ', '));
    else
        fprintf('  -> Interface OK, ready for ERT build\n');
    end
    fprintf('  -> JSON: %s\n', output_json_path);
    fprintf('============================================\n\n');

    bdclose(model_name);
end

function candidates = standard_name_candidates(ports, standard_names)
    candidates = {};
    for i = 1:length(ports)
        for j = 1:length(standard_names)
            if strcmp(ports{i}.name, standard_names{j})
                candidates{end+1} = struct('semantic', standard_names{j}, ...
                    'port', ports{i}.name, 'confidence', 'name_only'); %#ok<AGROW>
            end
        end
    end
end

function candidates = candidate_tunable_parameters(model_name)
    candidates = {};
    try
        workspace = get_param(model_name, 'ModelWorkspace');
        variables = workspace.whos;
        for i = 1:length(variables)
            if strcmp(variables(i).class, 'Simulink.Parameter')
                candidates{end+1} = struct('name', variables(i).name, ...
                    'source', 'model_workspace', 'requires_review', true); %#ok<AGROW>
            end
        end
    catch
    end
end

function write_contract_draft(interface_json_path, info)
    % This is intentionally not a deployable contract.  It gives the model
    % owner a reviewable starting point while retaining every uncertainty.
    [folder, name, ~] = fileparts(interface_json_path);
    draft = struct();
    draft.document_kind = 'hil_contract_draft';
    draft.schema_version = 1;
    draft.model_name = info.model_name;
    draft.source_interface = [name '.json'];
    draft.contract_review_required = true;
    draft.proposed = struct('state_outputs', {info.candidate_state_fields}, ...
        'input_bindings', {info.candidate_input_fields}, ...
        'parameters', {info.candidate_parameters});
    draft.unresolved_items = info.unresolved_items;
    draft.notes = {'This file is not accepted by the package validator.', ...
        'Units, ranges, frames, actuator bindings, source permissions and parameter classes require owner approval.'};
    fid = fopen(fullfile(folder, [info.model_name '_hil_contract_draft.json']), 'w');
    if fid < 0, error('Cannot write HIL contract draft'); end
    fprintf(fid, '%s', jsonencode(draft));
    fclose(fid);
end

function items = unresolved_items(inports, outports, state_candidates, input_candidates, parameters)
    items = {};
    matched = {};
    for i = 1:length(state_candidates), matched{end+1} = state_candidates{i}.port; end %#ok<AGROW>
    for i = 1:length(input_candidates), matched{end+1} = input_candidates{i}.port; end %#ok<AGROW>
    for i = 1:length(inports)
        if ~any(strcmp(matched, inports{i}.name))
            items{end+1} = struct('kind', 'input_port', 'name', inports{i}.name, ...
                'reason', 'physical_semantics_unit_and_range_require_review'); %#ok<AGROW>
        end
    end
    for i = 1:length(outports)
        if ~any(strcmp(matched, outports{i}.name))
            items{end+1} = struct('kind', 'output_port', 'name', outports{i}.name, ...
                'reason', 'physical_semantics_unit_and_range_require_review'); %#ok<AGROW>
        end
    end
    for i = 1:length(parameters)
        items{end+1} = struct('kind', 'parameter', 'name', parameters{i}.name, ...
            'reason', 'runtime_class_range_and_binding_require_review'); %#ok<AGROW>
    end
end
