import * as ubus from 'ubus';
import * as uloop from 'uloop';
import { create_guard } from './guard.uc';

export function run_guard(board, read, poweroff, checkpoint) {
    uloop.init();
    const bus = ubus.connect(null, 2);
    if (!bus) die('battery-guard: ubus unavailable\n');
    let guard;
    const timer = uloop.timer(-1, () => guard.tick());
    guard = create_guard(board, {
        read,
        schedule: delay => timer.set(delay),
        cancel: () => timer.set(-1),
        poweroff,
    });
    const event = bus.listener('unisoc.battery', () => guard.event());
    if (!event) die('battery-guard: event subscription failed\n');
    let checkpoint_timer;
    if (checkpoint) {
        checkpoint_timer = uloop.timer(checkpoint.interval_ms, () => {
            checkpoint.tick();
            checkpoint_timer.set(checkpoint.interval_ms);
        });
        checkpoint.tick();
    }
    const stop = () => {
        if (checkpoint) checkpoint.tick();
        uloop.end();
    };
    const term = uloop.signal(15, stop);
    const interrupt = uloop.signal(2, stop);
    guard.event();  // Check boot state after subscribing, before blocking in epoll.
    uloop.run();
};
