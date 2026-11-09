/* SPDX-License-Identifier: GPL-2.0
 * SC2355 SDIO completion fixture from the registered Enceka kernel
 * 020b970e351eee3887e6caaf2d653926e7086e44. Scheduling/bus I/O are mocked.
 */
int sc2355_add_topop_list(int chn, struct mbuf_t *head,
			  struct mbuf_t *tail, int num)
{
	struct sprd_hif *hif = sc2355_get_hif();
	struct sprd_work *misc_work;
	struct pop_work pop_work;
	u8 *work_data = NULL;

	pop_work.chn = chn;
	pop_work.head = (void *)head;
	pop_work.tail = (void *)tail;
	pop_work.num = num;

	misc_work = sprd_alloc_work(sizeof(struct pop_work));
	if (!misc_work) {
		wl_err("%s out of memory\n", __func__);
		return -1;
	}
	misc_work->vif = NULL;
	misc_work->id = SPRD_POP_MBUF;
	work_data = misc_work->data;
	memcpy(work_data, &pop_work, sizeof(struct pop_work));

	sprd_queue_work(hif->priv, misc_work);
	return 0;
}
