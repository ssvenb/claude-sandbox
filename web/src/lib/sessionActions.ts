// Ending a session, as each of its pages does it. Closing a tab leaves a session running; only
// these end it. Stopping removes its container and keeps it listed, to read how it ended and to
// resume it. Deleting forgets it, and closes its tabs.
import { message } from '../api/client';
import { deleteSession, getOffers, stopSession } from '../api/sessions';
import type { Offer, Session } from '../api/types';

/** Stops a session once `question` is answered yes. Says whether it was asked to stop. */
export async function stopAfterAsking(s: Session, question: string): Promise<boolean> {
  if (!confirm(question)) return false;
  await stopSession(s.id).catch(e => alert(message(e)));
  return true;
}

/** Deletes a session (one still running only once `question` is answered yes). What a plugin
 *  offers to tidy up with it (its run's open pull request: close it) is asked about one by one,
 *  and done only on a yes. Says whether it went ahead. */
export async function deleteAfterAsking(s: Session, question: string): Promise<boolean> {
  if (s.exit === null && !confirm(question)) return false;
  const { offers } = await getOffers(s.id).catch(() => ({ offers: [] as Offer[] }));
  const tidy = offers.filter(o => confirm(o.ask)).map(o => o.url);
  const done = await deleteSession(s.id, tidy).catch(e => alert(message(e)));
  if (done?.failed?.length) alert('Not done:\n' + done.failed.join('\n'));
  return true;
}
