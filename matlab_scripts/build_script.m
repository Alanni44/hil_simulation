function build_script(task_file, result_file)

    fprintf('[MATLAB] Build script started\n');
    fprintf('[MATLAB] Task file: %s\n', task_file);

    try
        fid = fopen(task_file, 'r');
        task_json = fread(fid, '*char')';
        fclose(fid);
        task = jsondecode(task_json);
    catch ME
        write_result(result_file, -1, sprintf('Failed to read task: %s', ME.message));
        return;
    end

    model_name = task.model_name;
    slx_path = task.slx_path;
    output_dir = task.output_dir;
    lib_name = task.lib_name;

    fprintf('[MATLAB] Model: %s\n', model_name);
    fprintf('[MATLAB] SLX: %s\n', slx_path);

    try
        load_system(slx_path);
        fprintf('[MATLAB] Model loaded\n');
    catch ME
        write_result(result_file, -1, sprintf('Failed to load: %s', ME.message));
        return;
    end

    try
        set_param(model_name, 'SystemTargetFile', 'ert.tlc');
        set_param(model_name, 'TargetLang', 'C');
        set_param(model_name, 'GenerateComments', 'on');
        set_param(model_name, 'GenerateReport', 'on');
        set_param(model_name, 'GenerateCodeOnly', 'on');
        set_param(model_name, 'SolverType', 'Fixed-step');
        set_param(model_name, 'Solver', 'FixedStepDiscrete');
        set_param(model_name, 'FixedStep', '0.001');
        set_param(model_name, 'ParameterTuning', 'on');
        fprintf('[MATLAB] Configured\n');
    catch ME
        write_result(result_file, -1, sprintf('Config failed: %s', ME.message));
        return;
    end

    try
        v = version('-release');
        ver_num = str2double(v(2:5));
        if ver_num >= 2019
            cfg = coder.config('lib');
            cfg.GenCodeOnly = true;
            cfg.TargetLang = 'C';
            slbuild(model_name, cfg);
        else
            rtwbuild(model_name);
        end
        fprintf('[MATLAB] Code generated\n');
    catch ME
        write_result(result_file, -1, sprintf('Generation failed: %s', ME.message));
        return;
    end

    try
        code_dir = fullfile(output_dir, [model_name '_ert_rtw']);
        if ~exist(code_dir, 'dir')
            code_dir = output_dir;
        end
        c_files = dir(fullfile(code_dir, '*.c'));
        if isempty(c_files)
            error('No C files found');
        end
        libs_dir = fullfile(fileparts(output_dir), 'libs');
        mkdir(libs_dir);
        so_path = fullfile(libs_dir, [lib_name '.so']);
        cmd = 'gcc -shared -fPIC -O2 -I"' code_dir '"';
        for i = 1:length(c_files)
            cmd = [cmd ' "' fullfile(code_dir, c_files(i).name) '"'];
        end
        cmd = [cmd ' -lm -o "' so_path '"'];
        fprintf('[MATLAB] Compiling: %s\n', cmd);
        [status, output] = system(cmd);
        if status ~= 0
            error('Compile failed: %s', output);
        end
        fprintf('[MATLAB] SO created: %s\n', so_path);
    catch ME
        write_result(result_file, -1, sprintf('Compile failed: %s', ME.message));
        return;
    end

    result = struct('code', 0, 'message', 'Build successful', ...
                    'so_path', so_path, 'model_name', model_name, ...
                    'timestamp', datestr(now, 'yyyy-mm-dd HH:MM:SS'));
    write_result_json(result_file, result);
    fprintf('[MATLAB] Build complete\n');
    bdclose(model_name);
end

function write_result_json(filename, data)
    fid = fopen(filename, 'w');
    fprintf(fid, '%s', jsonencode(data));
    fclose(fid);
end

function write_result(filename, code, message)
    data = struct('code', code, 'message', message);
    write_result_json(filename, data);
end