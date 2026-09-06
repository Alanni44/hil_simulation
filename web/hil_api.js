(function (global) {
  'use strict';
  function HilApi() { this.socket = null; this.pending = null; }
  HilApi.prototype.connect = function (url) {
    var self = this;
    return new Promise(function (resolve, reject) {
      var socket = new WebSocket(url);
      socket.onopen = function () { self.socket = socket; resolve(); };
      socket.onerror = function () { reject(new Error('无法连接 HIL WebSocket 服务。')); };
      socket.onmessage = function (event) {
        var reply;
        try { reply = JSON.parse(event.data); } catch (error) { return; }
        if (self.pending) { var pending = self.pending; self.pending = null; pending.resolve(reply); }
      };
      socket.onclose = function () { self.socket = null; if (self.pending) { self.pending.reject(new Error('服务连接已关闭。')); self.pending = null; } };
    });
  };
  HilApi.prototype.request = function (cmd, params) {
    var self = this;
    return new Promise(function (resolve, reject) {
      if (!self.socket || self.socket.readyState !== WebSocket.OPEN) { reject(new Error('尚未连接服务。')); return; }
      if (self.pending) { reject(new Error('请等待上一项操作完成。')); return; }
      self.pending = { resolve: resolve, reject: reject };
      self.socket.send(JSON.stringify({ cmd: cmd, params: params || {} }));
    });
  };
  global.HilApi = HilApi;
}(window));
