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
%   root_inports      - 根级 Inport 列表 [{name, port}]
%   root_outports     - 根级 Outport 列表 [{name, port}]
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
    info.solver = get_param(model_name, 'Solver');
    info.solver_type = get_param(model_name, 'SolverType');
    info.fixed_step = get_param(model_name, 'FixedStep');
    info.system_target = get_param(model_name, 'SystemTargetFile');
    info.stop_time = get_param(model_name, 'StopTime');
    info.target_lang = get_param(model_name, 'TargetLang');

    % ---- Root-level Inports ----
    inports = find_system(model_name, 'SearchDepth', 1, 'BlockType', 'Inport');
    info.root_inports = {};
    for i = 1:length(inports)
        name = get_param(inports{i}, 'Name');
        port_str = get_param(inports{i}, 'Port');
        port_num = str2double(port_str);
        info.root_inports{end+1} = struct('name', name, 'port', port_num);
    end

    % ---- Root-level Outports ----
    outports = find_system(model_name, 'SearchDepth', 1, 'BlockType', 'Outport');
    info.root_outports = {};
    for i = 1:length(outports)
        name = get_param(outports{i}, 'Name');
        port_str = get_param(outports{i}, 'Port');
        port_num = str2double(port_str);
        info.root_outports{end+1} = struct('name', name, 'port', port_num);
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

    % ---- Write JSON ----
    fid = fopen(output_json_path, 'w');
    if fid < 0
        error('Cannot write to: %s', output_json_path);
    end
    fprintf(fid, '%s', jsonencode(info));
    fclose(fid);

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
