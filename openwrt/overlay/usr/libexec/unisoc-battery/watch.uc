import { profile, sample } from './adapter.uc';
import { run_guard } from './events.uc';
import { start_checkpoint } from './checkpoint.uc';

const board = profile();
if (!board) exit(0);
run_guard(board, () => sample(), reason => {
    print('battery-guard: requesting orderly poweroff (' + reason + ')\n');
    // No forced reboot/poweroff: procd stops services and unmounts normally.
    if (system('/sbin/poweroff') != 0)
        die('battery-guard: poweroff failed\n');
}, start_checkpoint());
