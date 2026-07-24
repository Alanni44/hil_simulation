function generate_test_model(output_dir)
% GENERATE_TEST_MODEL  R2018b-compatible Simulink model generator for HIL pipeline test.
%   generate_test_model(output_dir) creates output_dir/hil_test_model.slx
%
%   The model implements a simplified discrete 6DOF drone with PID control.
%   Interface names match the alias tables in adapt_model.m:
%     Inports:  cmd_x, cmd_y, cmd_z, cmd_yaw, cmd_mode, cmd_speed
%     Outports: pos_x, pos_y, pos_z, roll, pitch, yaw, vel_x, vel_y, vel_z, airborne
%     Tunable  Constants: u_mass, u_gravity, u_drag_x, u_drag_y,
%                          u_kpz, u_kiz, u_kdz, u_kpxy, u_kixy, u_kdxy
%     Scopes:  Scope_pos_x, Scope_pos_y, Scope_pos_z,
%              Scope_roll, Scope_pitch, Scope_yaw

    if nargin < 1, output_dir = pwd; end
    if ~exist(output_dir, 'dir'), mkdir(output_dir); end

    mdl = 'hil_test_model';
    try close_system(mdl, 0); catch, end

    new_system(mdl);
    open_system(mdl);

    set_param(mdl, 'SolverType', 'Fixed-step');
    set_param(mdl, 'Solver', 'FixedStepDiscrete');
    set_param(mdl, 'FixedStep', '0.001');
    set_param(mdl, 'StopTime', 'inf');

    % ---- Root Inports ----
    ports  = {'cmd_x','cmd_y','cmd_z','cmd_yaw','cmd_mode','cmd_speed'};
    for i = 1:6
        add_block('simulink/Sources/In1', [mdl '/' ports{i}]);
        set_param([mdl '/' ports{i}], 'Port', int2str(i));
    end

    % ---- Root Outports (avoid naming conflict with Drone internals) ----
    routs  = {'X','Y','Z','Phi','Theta','Psi','vx','vy','vz','airborne'};
    % adapt_model aliases map these to: pos_x, pos_y, pos_z, roll, pitch, yaw, vel_x, vel_y, vel_z, airborne
    for i = 1:10
        add_block('simulink/Sinks/Out1', [mdl '/' routs{i}]);
        set_param([mdl '/' routs{i}], 'Port', int2str(i));
    end

    % ---- Tunable Constants (u_ prefix for adapt_model recognition) ----
    tun    = {'u_mass','0.65'; 'u_gravity','9.81'; 'u_drag_x','0.05'; 'u_drag_y','0.05'; ...
              'u_kpz','2.5'; 'u_kiz','0.05'; 'u_kdz','1.2'; ...
              'u_kpxy','1.5'; 'u_kixy','0.02'; 'u_kdxy','0.8'};
    for i = 1:size(tun,1)
        add_block('simulink/Sources/Constant', [mdl '/' tun{i,1}], 'Value', tun{i,2});
    end

    % ---- Root Scopes ----
    add_block('simulink/Sinks/Scope', [mdl '/X'], 'Position', [600,25,630,55]);
    add_block('simulink/Sinks/Scope', [mdl '/Y'], 'Position', [600,60,630,90]);
    add_block('simulink/Sinks/Scope', [mdl '/Z'], 'Position', [600,95,630,125]);
    add_block('simulink/Sinks/Scope', [mdl '/Phi'], 'Position', [600,130,630,160]);
    add_block('simulink/Sinks/Scope', [mdl '/Theta'], 'Position', [600,165,630,195]);
    add_block('simulink/Sinks/Scope', [mdl '/Psi'], 'Position', [600,200,630,230]);

    % ======== Drone SubSystem ========
    sys    = [mdl '/Drone'];
    add_block('simulink/Ports & Subsystems/Subsystem', sys);

    % Delete SubSystem default I/O
    din = find_system(sys, 'SearchDepth', 1, 'BlockType', 'Inport');
    dout = find_system(sys, 'SearchDepth', 1, 'BlockType', 'Outport');
    for k = 1:length(din), delete_block(din{k}); end
    for k = 1:length(dout), delete_block(dout{k}); end
    subin  = {'cmd_x','cmd_y','cmd_z','cmd_yaw','cmd_mode','cmd_speed', ...
              'mass','gravity','drag_x','drag_y','kpz','kiz','kdz','kpxy','kixy','kdxy'};
    for i = 1:16
        add_block('simulink/Sources/In1', [sys '/' subin{i}], 'Port', num2str(i));
    end

    % Sub outports
    sout   = {'pos_x','pos_y','pos_z','roll','pitch','yaw','vel_x','vel_y','vel_z','airborne'};
    for i = 1:10
        add_block('simulink/Sinks/Out1', [sys '/' sout{i}], 'Port', num2str(i));
    end

    % ---- PID error = cmd - feedback ----
    add_block('simulink/Math Operations/Add', [sys '/err_X'], 'Inputs','+-');
    add_block('simulink/Math Operations/Add', [sys '/err_Y'], 'Inputs','+-');
    add_block('simulink/Math Operations/Add', [sys '/err_Z'], 'Inputs','+-');

    % ---- P Gain ----
    add_block('simulink/Math Operations/Gain', [sys '/P_X'],  'Gain','kpxy');
    add_block('simulink/Math Operations/Gain', [sys '/P_Y'],  'Gain','kpxy');
    add_block('simulink/Math Operations/Gain', [sys '/P_Z'],  'Gain','kpz');

    % ---- I: err*kixy/kiz -> discrete-time integrator ----
    add_block('simulink/Math Operations/Gain', [sys '/Ig_X'], 'Gain','kixy');
    add_block('simulink/Math Operations/Gain', [sys '/Ig_Y'], 'Gain','kixy');
    add_block('simulink/Math Operations/Gain', [sys '/Ig_Z'], 'Gain','kiz');
    add_block('simulink/Discrete/Discrete-Time Integrator', [sys '/I_X'], 'gainval','0.001');
    add_block('simulink/Discrete/Discrete-Time Integrator', [sys '/I_Y'], 'gainval','0.001');
    add_block('simulink/Discrete/Discrete-Time Integrator', [sys '/I_Z'], 'gainval','0.001');

    % ---- D: discrete derivative * kdxy/kdz ----
    add_block('simulink/Discrete/Discrete Derivative', [sys '/Deriv_X']);
    add_block('simulink/Discrete/Discrete Derivative', [sys '/Deriv_Y']);
    add_block('simulink/Discrete/Discrete Derivative', [sys '/Deriv_Z']);
    add_block('simulink/Math Operations/Gain', [sys '/Dg_X'], 'Gain','kdxy');
    add_block('simulink/Math Operations/Gain', [sys '/Dg_Y'], 'Gain','kdxy');
    add_block('simulink/Math Operations/Gain', [sys '/Dg_Z'], 'Gain','kdz');

    % ---- PID Sum ----
    add_block('simulink/Math Operations/Add', [sys '/PID_X'], 'Inputs','+++');
    add_block('simulink/Math Operations/Add', [sys '/PID_Y'], 'Inputs','+++');
    add_block('simulink/Math Operations/Add', [sys '/PID_Z'], 'Inputs','+++');

    % ---- Saturation ----
    add_block('simulink/Discontinuities/Saturation', [sys '/Sat_X'],   'UpperLimit','15','LowerLimit','-15');
    add_block('simulink/Discontinuities/Saturation', [sys '/Sat_Y'],   'UpperLimit','15','LowerLimit','-15');
    add_block('simulink/Discontinuities/Saturation', [sys '/Sat_Z'],   'UpperLimit','10','LowerLimit','-10');
    add_block('simulink/Discontinuities/Saturation', [sys '/Sat_yaw'], 'UpperLimit','pi','LowerLimit','-pi');

    % ---- Velocity integrator: vel -> pos ----
    add_block('simulink/Discrete/Discrete-Time Integrator', [sys '/Pos_X'], 'gainval','0.001');
    add_block('simulink/Discrete/Discrete-Time Integrator', [sys '/Pos_Y'], 'gainval','0.001');
    add_block('simulink/Discrete/Discrete-Time Integrator', [sys '/Pos_Z'], 'gainval','0.001');

    % ---- Yaw integrator ----
    add_block('simulink/Discrete/Discrete-Time Integrator', [sys '/Int_yaw'], 'gainval','0.001');

    % ---- Roll/Pitch = 0 (stub) ----
    add_block('simulink/Sources/Constant', [sys '/zero_rp'], 'Value','0');

    % ---- Airborne = pos_z > 0.5 ----
    add_block('simulink/Logic and Bit Operations/Compare To Constant', [sys '/Airborne'], ...
              'relop','>','const','0.5');

    % ---- Feedback Unit Delays ----
    add_block('simulink/Discrete/Unit Delay', [sys '/FB_X'], 'SampleTime','0.001');
    add_block('simulink/Discrete/Unit Delay', [sys '/FB_Y'], 'SampleTime','0.001');
    add_block('simulink/Discrete/Unit Delay', [sys '/FB_Z'], 'SampleTime','0.001');

    % ======== Internal wiring ========

    % err: cmd(+) feedback(-)
    add_line(sys,'cmd_x/1','err_X/1'); add_line(sys,'FB_X/1','err_X/2');
    add_line(sys,'cmd_y/1','err_Y/1'); add_line(sys,'FB_Y/1','err_Y/2');
    add_line(sys,'cmd_z/1','err_Z/1'); add_line(sys,'FB_Z/1','err_Z/2');

    % X chain
    add_line(sys,'err_X/1','P_X/1'); add_line(sys,'err_X/1','Ig_X/1'); add_line(sys,'err_X/1','Deriv_X/1');
    add_line(sys,'Ig_X/1','I_X/1'); add_line(sys,'Deriv_X/1','Dg_X/1');
    add_line(sys,'P_X/1','PID_X/1'); add_line(sys,'I_X/1','PID_X/2'); add_line(sys,'Dg_X/1','PID_X/3');
    add_line(sys,'PID_X/1','Sat_X/1'); add_line(sys,'Sat_X/1','Pos_X/1');
    add_line(sys,'Pos_X/1','FB_X/1');
    add_line(sys,'Pos_X/1','pos_x/1'); add_line(sys,'Sat_X/1','vel_x/1');

    % Y chain
    add_line(sys,'err_Y/1','P_Y/1'); add_line(sys,'err_Y/1','Ig_Y/1'); add_line(sys,'err_Y/1','Deriv_Y/1');
    add_line(sys,'Ig_Y/1','I_Y/1'); add_line(sys,'Deriv_Y/1','Dg_Y/1');
    add_line(sys,'P_Y/1','PID_Y/1'); add_line(sys,'I_Y/1','PID_Y/2'); add_line(sys,'Dg_Y/1','PID_Y/3');
    add_line(sys,'PID_Y/1','Sat_Y/1'); add_line(sys,'Sat_Y/1','Pos_Y/1');
    add_line(sys,'Pos_Y/1','FB_Y/1');
    add_line(sys,'Pos_Y/1','pos_y/1'); add_line(sys,'Sat_Y/1','vel_y/1');

    % Z chain
    add_line(sys,'err_Z/1','P_Z/1'); add_line(sys,'err_Z/1','Ig_Z/1'); add_line(sys,'err_Z/1','Deriv_Z/1');
    add_line(sys,'Ig_Z/1','I_Z/1'); add_line(sys,'Deriv_Z/1','Dg_Z/1');
    add_line(sys,'P_Z/1','PID_Z/1'); add_line(sys,'I_Z/1','PID_Z/2'); add_line(sys,'Dg_Z/1','PID_Z/3');
    add_line(sys,'PID_Z/1','Sat_Z/1'); add_line(sys,'Sat_Z/1','Pos_Z/1');
    add_line(sys,'Pos_Z/1','FB_Z/1');
    add_line(sys,'Pos_Z/1','pos_z/1'); add_line(sys,'Sat_Z/1','vel_z/1');
    add_line(sys,'Pos_Z/1','Airborne/1');
    add_line(sys,'Airborne/1','airborne/1');

    % Yaw
    add_line(sys,'cmd_yaw/1','Int_yaw/1');
    add_line(sys,'Int_yaw/1','Sat_yaw/1');
    add_line(sys,'Sat_yaw/1','yaw/1');

    % Roll/Pitch = 0
    add_line(sys,'zero_rp/1','roll/1');
    add_line(sys,'zero_rp/1','pitch/1');

    % ======== Root wiring: Inports + Constants -> Drone -------
    for i = 1:6
        add_line(mdl, [ports{i} '/1'], ['Drone/' num2str(i)]);
    end
    for i = 1:10
        add_line(mdl, [tun{i,1} '/1'], ['Drone/' num2str(6+i)]);
    end

    % Drone -> root Outports
    for i = 1:10
        add_line(mdl, ['Drone/' num2str(i)], [routs{i} '/1']);
    end

    % Drone -> Scopes (match root Outport names)
    add_line(mdl, 'Drone/1', 'X/1');
    add_line(mdl, 'Drone/2', 'Y/1');
    add_line(mdl, 'Drone/3', 'Z/1');
    add_line(mdl, 'Drone/4', 'Phi/1');
    add_line(mdl, 'Drone/5', 'Theta/1');
    add_line(mdl, 'Drone/6', 'Psi/1');

    % Save
    slx_file = fullfile(output_dir, [mdl '.slx']);
    save_system(mdl, slx_file);
    close_system(mdl, 0);
    fprintf('[generate_test_model] Created: %s\n', slx_file);
end
