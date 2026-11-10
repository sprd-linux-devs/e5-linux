'use strict';
// SPDX-License-Identifier: MIT
// Adapted from XiaoMengXinX/e5-webapp-esim@11b10358; see LICENSE and ORIGIN.json.
import { access } from 'fs';

function quote(value) { return "'" + replace(value, /'/g, "'\\''") + "'"; }

return function(ctx) {
 function status() {
  let installed = access('/usr/lib/lpac', 1) && access('/usr/libexec/unisoc-modem/euicc', 1);
  return { installed: !!installed, installing: false,
   error: installed ? null : 'eSIM components are missing; install the current complete firmware.' };
 }
 return {
  'GET /status': status,
  // Dependencies are part of the firmware. Never start a hidden package installer.
  'GET /notifications': function() { return { notifications: [] }; },
  'POST /rpc': function(req) {
   if (type(req.body) != 'object' || type(req.body.method) != 'string' || type(req.body.params) != 'object')
    return { ok: false, error: 'invalid_request' };
   let output = ctx.sh(`printf '%s' ${quote(sprintf('%J', req.body))} | /usr/libexec/unisoc-modem/euicc screen_rpc`);
   try { return json(output); }
   catch (e) { return { ok: false, error: 'backend', detail: 'eSIM service unavailable' }; }
  }
 };
};
