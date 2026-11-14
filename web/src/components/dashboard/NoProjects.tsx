/** In place of the board while no project is listed: where to list them. */
export function NoProjects({ file }: { file?: string }) {
  return (
    <div className="empty">
      <b>No projects yet</b>
      List the directories of the repos your agents work on, one per line, in {file}.
    </div>
  );
}
