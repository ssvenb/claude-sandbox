/** In place of a session that is no longer there. */
export function Gone({ id, hidden }: { id: string; hidden: boolean }) {
  return (
    <div id={id} hidden={hidden}>
      <div>
        <b>Session gone</b>
        <a href="/">Dashboard</a>
      </div>
    </div>
  );
}
