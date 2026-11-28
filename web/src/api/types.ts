// What src/server/server.py says and takes, named for the page: generated from its own description
// (schema.ts, from src/server/models.py), so a change to a route's shape is a type error here.
import type * as Api from './schema';

export type { Json, JsonObject } from './schema';

export type Session = Api.Session;
export type SessionKind = Session['kind'];
export type SessionStatus = NonNullable<Session['status']>;
export type AppState = Api.AppState;
export type NewSession = Api.NewSession;

export type Item = Api.Item;
export type ItemStatus = NonNullable<Item['status']>;
export type ItemList = Api.ItemList;
/** What a project's plugins say about it (`run.sh --web`). */
export type ProjectInfo = Api.ProjectInfo;
/** What deleting a session offers to tidy up with it, a yes/no each. */
export type Offer = Api.Offer;

/** A picture pasted into a message: its media type and its bytes in base64. Held in the tray, it may
 *  be any file attached by hand, then with its name: what is not a picture goes as a file. */
export type Picture = Api.Picture;
export type Upload = Api.Upload;

// ---- settings -------------------------------------------------------------------------------

export type SettingSpec = Api.SettingSpec;
export type SettingType = NonNullable<SettingSpec['type']>;
export type SettingsPart = Api.SettingsPart;
export type PluginManifest = Api.PluginManifest;
export type ProjectConfig = Api.ProjectConfig;

export type AuthFileInfo = Api.AuthFileInfo;
export type AuthConfig = Api.AuthConfig;
