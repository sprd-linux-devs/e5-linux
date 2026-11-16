"""Wire the vendor SPRD host DMA backend into the upstream host scheduler."""
from pathlib import Path


def gadget_udc_api(text):
    """Keep the UDC core's private layout out of the vendor role driver."""
    private = '''struct sprd_usb_udc {
\tstruct usb_gadget_driver\t*driver;
\tstruct usb_gadget\t\t*gadget;
\tstruct device\t\t\tdev;
\tstruct list_head\t\tlist;
\tbool\t\t\t\tvbus;
\tbool\t\t\t\tstarted;
};

'''
    old = '''\t\tstruct sprd_usb_udc *sprd_udc = (struct sprd_usb_udc *)musb->g.udc;
\t\tstruct usb_gadget *gadget = &musb->g;'''
    new = '\t\tstruct usb_gadget *gadget = &musb->g;'
    stop = '''\t\tif (sprd_udc)
\t\t\tsprd_udc->vbus = false;

\t\tgadget->ops->pullup(gadget, 0);'''
    public = '''\t\t/* UDC internals change across kernels. Publish VBUS through the
\t\t * core API and finish the disconnect before the role powers down.
\t\t * This also keeps gadget->connected in sync with the pullup.
\t\t */
\t\tusb_udc_vbus_handler(gadget, false);
\t\tusb_gadget_disconnect(gadget);'''
    if public in text:
        assert 'struct sprd_usb_udc' not in text, 'Stale private UDC layout'
        return text
    for before, after in ((private, ''), (old, new), (stop, public)):
        assert text.count(before) == 1, 'Unexpected vendor UDC disconnect'
        text = text.replace(before, after, 1)
    return text


def apply(kernel):
    # SPRD owns HCD registration in its role worker. Registering here too
    # leaks the probe-time root hub and lets two hubs suspend the same core.
    core = kernel / 'drivers/usb/musb/musb_core.c'
    text = core.read_text()
    old = ('\tcase MUSB_OTG:\n'
           '\t\tstatus = musb_host_setup(musb, plat->power);\n'
           '\t\tif (status < 0)\n\t\t\tgoto fail3;')
    new = ('\tcase MUSB_OTG:\n'
           '\t\t/* SPRD registers the HCD when its role worker enters host. */\n'
           '\t\tif (!(musb->ops->quirks & MUSB_DMA_SPRD)) {\n'
           '\t\t\tstatus = musb_host_setup(musb, plat->power);\n'
           '\t\t\tif (status < 0)\n\t\t\t\tgoto fail3;\n\t\t}')
    if new not in text:
        assert text.count(old) == 1, 'Unexpected OTG probe registration'
        text = text.replace(old, new, 1)
    # CC, not the generic MUSB OTG FSM, starts sessions on SPRD. Binding a
    # gadget with no cable puts the core in B_IDLE. musb_start() otherwise
    # asserts SESSION there, and IRQ work takes a separate runtime-PM hold;
    # the glue then cannot suspend before its first real host transition.
    start = text.index('void musb_start(')
    end = text.index('\n/*', start)
    body = text[start:end]
    old = '\t} else {\n\t\tdevctl |= MUSB_DEVCTL_SESSION;\n\t}\n'
    new = '''\t} else if (!(musb->ops->quirks & MUSB_DMA_SPRD) ||
\t\t   musb->port_mode != MUSB_OTG ||
\t\t   musb_get_state(musb) != OTG_STATE_B_IDLE) {
\t\t/* SPRD CC owns role selection. An unconnected gadget must not
\t\t * create a host session and pin runtime PM before CC selects host.
\t\t */
\t\tdevctl |= MUSB_DEVCTL_SESSION;
\t}
'''
    if new not in body:
        assert body.count(old) == 1, 'Unexpected MUSB session startup'
        body = body.replace(old, new, 1)
        text = text[:start] + body + text[end:]
    # The vendor role worker takes/releases the controller reference around
    # each real peripheral/host session. DEVCTL is not its cable detector:
    # after a cold gadget bind it can stay at 0x99 with no external VBUS.
    # Generic IRQ session accounting then pins the child, preventing glue
    # autosuspend and therefore the first CC-selected host transition.
    start = text.index('static void musb_pm_runtime_check_session(')
    end = text.index('\nstatic ', start + 10)
    body = text[start:end]
    marker = '\tdevctl = musb_readb(musb->mregs, MUSB_DEVCTL);'
    guard = '''\t/* SPRD role work owns runtime PM, including real host/peripheral
\t * sessions. A retained DEVCTL SESSION must not add another owner.
\t */
\tif (musb->ops->quirks & MUSB_DMA_SPRD)
\t\treturn;

'''
    if guard not in body:
        assert body.count(marker) == 1, 'Unexpected MUSB session PM accounting'
        body = body.replace(marker, guard + marker, 1)
        text = text[:start] + body + text[end:]
    core.write_text(text)

    # last_event can still contain the previous CC host notification when
    # configfs restarts the gadget after returning to device mode. SPRD's
    # glue owns VBUS; the generic SRP callback must not restart source mode.
    gadget = kernel / 'drivers/usb/musb/musb_gadget.c'
    text = gadget.read_text()
    old = '\tif (musb->xceiv && musb->xceiv->last_event == USB_EVENT_ID)'
    new = ('\tif (!(musb->ops->quirks & MUSB_DMA_SPRD) &&\n'
           '\t    musb->xceiv && musb->xceiv->last_event == USB_EVENT_ID)')
    if new not in text:
        assert text.count(old) == 1, 'Unexpected gadget VBUS startup'
        text = text.replace(old, new, 1)
    gadget.write_text(text)

    # DRD does not run musb_start() from the root hub's POWER request:
    # musb_has_gadget() only accepts a host-only port. The vendor host_start
    # callback was not ported, so SESSION alone left gadget/suspend register
    # state behind and could never reliably enumerate a newly attached NIC.
    glue = kernel / 'drivers/usb/musb/musb_sprd.c'
    text = gadget_udc_api(glue.read_text())
    start = text.index('static int musb_sprd_otg_start_host(')
    end = text.index('\nstatic ', start + 10)
    body = text[start:end]
    if 'musb_start(musb);' not in body:
        a = body.index('\t\tMUSB_HST_MODE(musb);')
        b = body.index('\n\t} else {', a)
        body = body[:a] + '''\t\tmusb_reset_all_fifo_2_default(musb);

\t\tglue->dr_mode = USB_DR_MODE_HOST;
\t\t/* Restore POWER and IRQ masks on every role transition. The DRD
\t\t * root hub does not start the core for us; SESSION/HOST_FORCE_EN
\t\t * alone retains stale peripheral suspend state.
\t\t */
\t\tspin_lock_irq(&musb->lock);
\t\tMUSB_HST_MODE(musb);
\t\tmusb->softconnect = 0;
\t\tmusb_set_state(musb, OTG_STATE_A_WAIT_BCON);
\t\tmusb_start(musb);
\t\tspin_unlock_irq(&musb->lock);
\t\tmusb_host_resume_root_hub(musb);''' + body[b:]
        text = text[:start] + body + text[end:]
    glue.write_text(text)

    path = kernel / 'drivers/usb/musb/musb_host.c'
    text = path.read_text()
    text = text.replace('/* SPRD host DMA is not wired into this host scheduler. */\n\t', '')
    text = text.replace('use_dma = !musb_dma_sprd(musb);', 'use_dma = 1;')
    if '#include "board-musb-sprd-host.h"' not in text:
        text = text.replace('static bool musb_tx_dma_program(',
                            '#include "board-musb-sprd-host.h"\n\nstatic bool musb_tx_dma_program(', 1)
        start = text.index('static bool musb_tx_dma_program(')
        end = text.index('\n/*\n * Program an HDRC endpoint', start)
        body = text[start:end]
        body = body.replace('\telse\n\t\treturn false;',
            '\telse if (musb_dma_sprd(hw_ep->musb)) {\n'
            '\t\tchannel->actual_len = 0;\n'
            '\t\tmode = !!(urb->transfer_flags & URB_ZERO_PACKET);\n'
            '\t} else\n\t\treturn false;', 1)
        body = body.replace('if (!dma->channel_program(', 'if (dma->channel_program(', 1)
        body = body.replace('urb->transfer_dma + offset, length)) {',
                            'urb->transfer_dma + offset, length) <= 0) {', 1)
        body = body.replace('\t\tdma->channel_release(channel);',
            '\t\tif (channel->status == MUSB_DMA_STATUS_BUSY)\n'
            '\t\t\tdma->channel_abort(channel);\n'
            '\t\tdma->channel_release(channel);', 1)
        body = body.replace('\treturn true;',
            '\tif (musb_dma_sprd(hw_ep->musb))\n\t\tmusb_sprd_tx_start(hw_ep);\n'
            '\treturn true;', 1)
        text = text[:start] + body + text[end:]
        start = text.rindex('static void musb_ep_program(struct musb *musb, u8 epnum,')
        end = text.index('\n/* Schedule next QH', start)
        body = text[start:end]
        # SPRD completion can precede final FIFO drain. Preserve CSR/toggle
        # state between descriptors instead of flushing the previous packet.
        a = body.index('\t\t\t/* flush all old state, set default */')
        b = body.index('\n\t\t} else {\n\t\t\t/* endpoint 0', a)
        block = body[a:b]
        body = body[:a] + '\t\t\tif (!musb_dma_sprd(musb)) {\n' + ''.join(
            '\t' + line + '\n' for line in block.splitlines()) + '\t\t\t}' + body[b:]
        marker = '\t\tif (hw_ep->rx_reinit) {'
        addition = ('\t\tif (musb_dma_sprd(musb) && dma_channel) {\n'
            '\t\t\tif (musb_sprd_rx_program(dma_channel, musb, epnum,\n'
            '\t\t\t\t\tqh, urb, offset, len))\n\t\t\t\treturn;\n'
            '\t\t\tdma_channel = NULL;\n\t\t}\n\n')
        assert body.count(marker) == 1
        body = body.replace(marker, addition + marker, 1)
        text = text[:start] + body + text[end:]
        # Let the controller maintain bulk toggles between DMA descriptors.
        start = text.index('static void musb_advance_schedule(')
        end = text.index('static u16 musb_h_flush_rxfifo', start)
        body = text[start:end]
        body = body.replace('case USB_ENDPOINT_XFER_BULK:\n\tcase USB_ENDPOINT_XFER_INT:',
            'case USB_ENDPOINT_XFER_BULK:\n\t\tif (musb_dma_sprd(musb))\n'
            '\t\t\tbreak;\n\t\tfallthrough;\n\tcase USB_ENDPOINT_XFER_INT:', 1)
        # Completion drops the lock; callbacks may have removed the queue.
        body = body.replace('\tmusb_giveback(musb, urb, status);\n\tqh->is_ready = ready;',
                            '\tmusb_giveback(musb, urb, status);', 1)
        body = body.replace('\tqh = musb_ep_get_qh(hw_ep, is_in);',
                            '\tqh = musb_ep_get_qh(hw_ep, is_in);\n'
                            '\tif (qh)\n\t\tqh->is_ready = ready;', 1)
        text = text[:start] + body + text[end:]
        text = text.replace('\tmusb->hops.tx_dma_program = musb_tx_dma_program;',
            '\tmusb->hops.tx_dma_program = musb_tx_dma_program;\n'
            '\tmusb->hops.rx_dma_program = musb_sprd_rx_next;', 1)
        text = text.replace('Only the two functions that exist in this tree are wired up -\n'
            '\t * hops.host_start and hops.rx_dma_program have no implementation here\n'
            '\t * and stay NULL, so every caller has to test for that.',
            'RX/TX DMA and completion are wired up here. hops.host_start\n'
            '\t * remains optional; the platform initializes the host controller.')
    text = text.replace('RX/TX DMA and completion are wired up here. hops.host_start\n'
                        '\t * remains optional; the platform initializes the host controller.',
                        'RX/TX DMA and completion are wired up here. The platform\n'
                        '\t * starts the core explicitly on every host role transition.')
    cleanup = ('\tif (musb->port_mode == MUSB_PERIPHERAL)\n\t\treturn;\n'
               '\tusb_remove_hcd(musb->hcd);')
    guarded = ('\tif (musb->port_mode == MUSB_PERIPHERAL ||\n'
               '\t    !musb->hcd->rh_registered)\n\t\treturn;\n'
               '\tusb_remove_hcd(musb->hcd);')
    if guarded not in text:
        assert text.count(cleanup) == 1, 'Unexpected HCD cleanup'
        text = text.replace(cleanup, guarded, 1)
    start = text.index('int musb_host_setup(')
    end = text.index('\nEXPORT_SYMBOL_GPL(musb_host_setup);', start)
    body = text[start:end]
    if 'if (hcd->rh_registered)' not in body:
        marker = '\tstruct usb_hcd *hcd = musb->hcd;\n'
        assert body.count(marker) == 1
        body = body.replace(marker, marker +
            '\n\t/* A repeated role notification must not register a second hub. */\n'
            '\tif (hcd->rh_registered)\n\t\treturn 0;\n', 1)
    # SPRD keeps a runtime-PM reference for the entire host session. Its
    # glue cannot autosuspend the root while waiting for attachment: the
    # generic bus_suspend sets SUSPENDM then returns EBUSY, and the hub's
    # zero autosuspend delay immediately retries. Keep only this root awake;
    # downstream device PM is unchanged and detach removes the root hub.
    marker = '\n\tdevice_wakeup_enable(hcd->self.controller);'
    if 'usb_disable_autosuspend(hcd->self.root_hub)' not in body:
        assert body.count(marker) == 1, 'Unexpected HCD PM initialization'
        body = body.replace(marker,
            '\n\t/* SPRD owns host-session PM; do not suspend the root during attach. */\n'
            '\tif (musb->ops->quirks & MUSB_DMA_SPRD)\n'
            '\t\tusb_disable_autosuspend(hcd->self.root_hub);\n' + marker, 1)
    text = text[:start] + body + text[end:]
    path.write_text(text)
    (path.parent / 'board-musb-sprd-host.h').write_bytes(
        Path(__file__).with_name('musb-sprd-host.h').read_bytes())
