/** In place of the board while no project is configured: where to configure them. */
export function NoProjects({ file }: { file?: string }) {
  return (
    <div className="empty">
      <b>No projects yet</b>
      Add a file per project to {file}: <code>my-app.json</code> holding <code>{'{"repo": "~/code/my-app"}'}</code>,
      a path on this machine or a git URL.
    </div>
  );
}
