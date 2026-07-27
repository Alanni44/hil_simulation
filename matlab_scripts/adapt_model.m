function result = adapt_model(slx_path, interface_json_path, contract_path, output_slx_path)
%ADAPT_MODEL Validate an explicit HIL contract without inferring semantics.
% The historical adapter matched aliases such as X/pos_x and inspected model
% blocks.  That is prohibited: delivery owners must declare every business
% mapping in hil_contract.json.

    if nargin < 4
        error('adapt_model requires SLX, interface JSON, contract JSON and output SLX');
    end
    info = read_json_object(interface_json_path, 'interface JSON');
    contract = read_json_object(contract_path, 'hil_contract.json');

    if ~isfield(contract, 'contract_version') || contract.contract_version ~= 1
        error('hil_contract.json contract_version must equal 1');
    end
    if ~isfield(contract, 'model_name') || ~strcmp(contract.model_name, info.model_name)
        error('contract.model_name must exactly match the top-level model name');
    end
    if ~isfield(contract, 'state') || ~isfield(contract.state, 'frame') || ...
            ~strcmp(contract.state.frame, 'NED') || ...
            ~isfield(contract.state, 'orientation') || ...
            ~strcmp(contract.state.orientation, 'FRD_TO_NED_QUATERNION')
        error('contract state must declare NED and FRD_TO_NED_QUATERNION');
    end
    if ~isfield(contract.state, 'outputs') || ~isfield(contract.state, 'units')
        error('contract state outputs and units are required');
    end

    required = required_state_fields();
    root_names = root_port_names(info.root_outports);
    mapping = struct();
    for i = 1:length(required)
        key = required{i};
        if ~isfield(contract.state.outputs, key) || ~ischar(contract.state.outputs.(key))
            error('contract missing state.outputs.%s', key);
        end
        if ~isfield(contract.state.units, key) || ...
                ~strcmp(contract.state.units.(key), required_unit(key))
            error('contract missing or invalid unit for %s', key);
        end
        declared = contract.state.outputs.(key);
        if ~any(strcmp(root_names, declared))
            error('contract output %s maps to nonexistent root Outport %s', key, declared);
        end
        mapping.(key) = declared;
    end
    declared_names = struct2cell(mapping);
    if length(unique(declared_names)) ~= length(declared_names)
        error('each required state key must map to a distinct root Outport');
    end

    % No topology mutation is permitted.  Copy only so codegen has its own
    % isolated work path; the copy preserves the exact customer model.
    copyfile(slx_path, output_slx_path);
    result = struct();
    result.adapted = false;
    result.field_mapping = struct('model_name', info.model_name, ...
        'outputs', mapping, 'contract_path', contract_path, 'adapted', false);
    result.warnings = {};

    [folder, ~, ~] = fileparts(output_slx_path);
    fid = fopen(fullfile(folder, 'field_mapping.json'), 'w');
    if fid < 0, error('Cannot write field_mapping.json'); end
    fprintf(fid, '%s', jsonencode(result.field_mapping));
    fclose(fid);
end

function value = read_json_object(path, label)
    fid = fopen(path, 'r');
    if fid < 0, error('Cannot read %s: %s', label, path); end
    value = jsondecode(fread(fid, '*char')');
    fclose(fid);
end

function names = root_port_names(ports)
    if iscell(ports)
        names = cellfun(@(port) port.name, ports, 'UniformOutput', false);
    else
        names = {ports.name};
    end
end

function fields = required_state_fields()
    fields = {'north_m','east_m','down_m','vn_mps','ve_mps','vd_mps', ...
        'q_w','q_x','q_y','q_z','p_radps','q_radps','r_radps','airborne'};
end

function unit = required_unit(field)
    units = struct('north_m','m','east_m','m','down_m','m', ...
        'vn_mps','m/s','ve_mps','m/s','vd_mps','m/s', ...
        'q_w','1','q_x','1','q_y','1','q_z','1', ...
        'p_radps','rad/s','q_radps','rad/s','r_radps','rad/s','airborne','bool');
    unit = units.(field);
end
