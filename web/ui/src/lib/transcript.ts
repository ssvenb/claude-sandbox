// A session's conversation, as its events left it. The events (api/events.ts) are kept as records,
// a column of them; each record carries a version that goes up whenever it, or anything inside
// it, changes, so drawing the page again redraws only what changed (see components/chat/Entry).
import type { AgentInfo, Answers, AskEvent, BackgroundTask, ChatEvent, PlanItem, Snapshot, ToolInput } from '../api/events';
import type { Picture, Session, SessionStatus } from '../api/types';

interface Base {
  key: number;
  /** Goes up whenever the record, or anything inside it, changes. */
  v: number;
  /** What holds it: the subagent call it belongs to, or the box a tool call is in. */
  up: ToolRecord | ToolsRecord | null;
}
export interface YouRecord extends Base { kind: 'you'; text: string; images?: Picture[]; queued: boolean }
export interface SayRecord extends Base { kind: 'say'; text: string; streaming: boolean }
export interface ThinkRecord extends Base { kind: 'think'; text: string; streaming: boolean }
/** A run of tool calls, in one box. */
export interface ToolsRecord extends Base { kind: 'tools'; list: ToolRecord[] }
export interface ToolRecord extends Base {
  kind: 'tool';
  name?: string;
  title?: string;
  input?: ToolInput;
  /** What a subagent said and did, inside the call that started it. */
  kids: Entry[];
  out: string;
  took: string;
  progress: string;
  done: boolean;
  error: boolean;
}
export interface AskRecord extends Base { kind: 'ask'; e: AskEvent; settled: boolean; answers?: Answers }
export interface TurnRecord extends Base { kind: 'turn'; text: string }
export interface NoteRecord extends Base { kind: 'note'; level: string; text: string }
export interface OverRecord extends Base { kind: 'over'; code: number; runId: string | null }

/** A record of the column. */
export type Entry = YouRecord | SayRecord | ThinkRecord | ToolsRecord | AskRecord | TurnRecord | NoteRecord | OverRecord;
type AnyRecord = Entry | ToolRecord;
type Block = SayRecord | ThinkRecord;
type Fields<R extends AnyRecord> = Omit<R, keyof Base | 'kind'> & { up?: Base['up'] };

/** The sandbox's own output while it starts: all of it, and its last line. */
export interface Boot {
  text: string;
  last: string;
}

const minutes = (seconds: number): string => `${Math.floor(seconds / 60)} min ${seconds % 60} s`;

// Something in a record changed: it, and whatever holds it, draw again.
function touch(r: AnyRecord | null): void {
  for (let at: AnyRecord | null = r; at; at = at.up) at.v++;
}

export class Transcript {
  session: Session | null = null;
  info: AgentInfo = {};
  status: SessionStatus = 'starting';
  ready = false;
  /** Its exit status, once it is over. */
  over: number | null = null;
  log: Entry[] = [];
  boot: Boot | null = null;
  todos: PlanItem[] | null = null;
  tasks: BackgroundTask[] = [];
  /** A model or effort picked here, until the agent says it took it. */
  chosen: { model?: string; effort?: string } = {};
  /** Something came that the reader should see (their own message, a question): the column
   *  follows its newest line again, wherever it was scrolled to. */
  wantsFollow = false;

  private blocks = new Map<string, Block>();
  private tools = new Map<string, ToolRecord>();
  private asks = new Map<string, AskRecord>();
  private users = new Map<string, YouRecord>();
  private uid = 0;

  /** The whole session from nothing: on opening the page, and whenever the stream reconnects. */
  restore(snap: Snapshot): void {
    this.log = [];
    this.blocks.clear();
    this.tools.clear();
    this.asks.clear();
    this.users.clear();
    this.boot = null;
    this.over = null;
    this.session = snap.session;
    this.info = { ...snap.info };
    this.ready = snap.ready;
    this.status = snap.status;
    this.bootLine('');
    for (const e of snap.events) this.handle(e);
    for (const b of this.blocks.values()) b.streaming = false;
    this.todos = snap.todos;
    this.tasks = snap.tasks ?? [];
    this.wantsFollow = true;
  }

  handle(e: ChatEvent): void {
    switch (e.type) {
      case 'boot': this.bootLine(e.text); break;
      case 'hello': this.info.agent = e.agent; break;
      case 'ready': { const { type: _, ...info } = e; Object.assign(this.info, info); this.ready = true; break; }
      case 'user': this.user(e); break;
      case 'sent': { const r = this.users.get(e.id); if (r) { r.queued = false; touch(r); } break; }
      case 'text': this.block(e, false); break;
      case 'delta': this.block(e, true); break;
      case 'tool': this.settleBlocks(); this.tool(e); break;
      case 'result': this.result(e); break;
      case 'progress': this.progress(e); break;
      case 'ask': this.settleBlocks(); this.ask(e); break;
      case 'asked': { const a = this.asks.get(e.id); if (a && !a.settled) this.settled(a, a.e.answers); break; }
      case 'turn': this.settleBlocks(); this.turn(e); break;
      case 'notice': this.place(this.record<NoteRecord>('note', { level: e.level || 'info', text: e.text })); break;
      case 'status': this.status = e.state; if (e.state !== 'working') this.settleBlocks(); break;
      case 'model': this.info.model = e.id; delete this.chosen.model; break;
      case 'effort': this.info.effort = e.level; delete this.chosen.effort; break;
      case 'todos': this.todos = e.items; break;
      case 'tasks': this.tasks = e.items ?? []; break;
      case 'exit': this.tasks = []; this.settleBlocks(); this.ended(e.code); break;
    }
  }

  /** The answer given here to a question, shown in its place once it is settled. */
  answered(id: string, answers: Answers): void {
    const a = this.asks.get(id);
    if (a) { a.e.answers = answers; touch(a); }
  }

  private record<R extends AnyRecord>(kind: R['kind'], fields: Fields<R>): R {
    return { kind, key: ++this.uid, v: 0, up: null, ...fields } as unknown as R;
  }

  // Where an event's record goes: inside the subagent call it belongs to, else at the column's end.
  private place<R extends Entry>(r: R, parent?: string): R {
    const t = (parent !== undefined && this.tools.get(parent)) || null;
    r.up = t;
    (t ? t.kids : this.log).push(r);
    touch(t);
    return r;
  }

  private bootLine(text: string): void {
    this.boot ??= { text: '', last: '' };
    if (text) {
      this.boot.text += text + '\n';
      this.boot.last = text.split('\n').filter(Boolean).pop() ?? '';
    }
  }

  private user(e: Extract<ChatEvent, { type: 'user' }>): void {
    const r = this.place(this.record<YouRecord>('you', { text: e.text, images: e.images, queued: !!e.queued }));
    if (e.id) this.users.set(e.id, r);
    // It is called what it was first asked.
    if (this.session && !this.session.title) this.session.title = e.text.replace(/\s+/g, ' ').slice(0, 140) || 'Image';
    this.wantsFollow = true;
  }

  // A block streams until its whole text comes, or until anything else does: not every block gets
  // its whole text sent (thinking may come only as a stream), and it must not turn for ever.
  private settleBlocks(except?: Block): void {
    for (const b of this.blocks.values()) if (b.streaming && b !== except) { b.streaming = false; touch(b); }
  }

  private block(e: Extract<ChatEvent, { type: 'text' | 'delta' }>, streaming: boolean): void {
    let b = this.blocks.get(e.id);
    if (!b) {
      b = this.place(this.record<Block>(e.kind === 'thinking' ? 'think' : 'say', { text: '', streaming }), e.parent);
      this.blocks.set(e.id, b);
    }
    this.settleBlocks(b);
    b.text = streaming ? b.text + e.text : e.text;
    b.streaming = streaming;
    touch(b);
  }

  private tool(e: Extract<ChatEvent, { type: 'tool' }>): void {
    let t = this.tools.get(e.id);
    if (!t) {
      const into = (e.parent !== undefined && this.tools.get(e.parent)?.kids) || this.log;
      let box = into[into.length - 1];
      if (box?.kind !== 'tools') box = this.place(this.record<ToolsRecord>('tools', { list: [] }), e.parent);
      t = this.record<ToolRecord>('tool', { up: box, kids: [], out: '', took: '', progress: '', done: false, error: false });
      box.list.push(t);
      this.tools.set(e.id, t);
    }
    Object.assign(t, { name: e.name ?? t.name, title: e.title ?? t.title, input: e.input ?? t.input, progress: '' });
    if (e.done !== undefined || e.output !== undefined) this.result(e);
    else touch(t);
  }

  private result(e: { id: string; output?: unknown; error?: boolean; done?: boolean; partial?: boolean }): void {
    const t = this.tools.get(e.id);
    if (!t) return;
    t.done = e.done ?? !e.partial;
    t.error = !!e.error;
    t.out = String(e.output ?? '').replace(/\s+$/, '');
    touch(t);
  }

  private progress(e: Extract<ChatEvent, { type: 'progress' }>): void {
    const t = this.tools.get(e.id);
    if (!t || t.done) return;
    if (e.seconds) t.took = e.seconds >= 60 ? minutes(e.seconds) : `${e.seconds} s`;
    if (e.text) t.progress = e.text;
    touch(t);
  }

  // Nothing still runs once a turn, or the session, is over.
  private finish(error = false): void {
    for (const t of this.tools.values()) if (!t.done) { t.done = true; t.error ||= error; touch(t); }
  }

  private ask(e: AskEvent): void {
    const a = this.place(this.record<AskRecord>('ask', { e, settled: false }));
    this.asks.set(e.id, a);
    if (e.done || e.answers !== undefined) this.settled(a, e.answers);
    else this.wantsFollow = true;
  }

  private settled(a: AskRecord, answers: Answers | undefined): void {
    a.settled = true;
    a.answers = answers;
    touch(a);
  }

  private turn(e: Extract<ChatEvent, { type: 'turn' }>): void {
    const parts: string[] = [];
    if (e.duration) {
      parts.push(e.duration >= 60000 ? `${Math.floor(e.duration / 60000)} min ${Math.round((e.duration % 60000) / 1000)} s`
        : `${Math.max(1, Math.round(e.duration / 1000))} s`);
    }
    if (typeof e.cost === 'number') parts.push(`$${e.cost.toFixed(2)}`);
    if (e.context?.max) parts.push(`${Math.round((100 * e.context.used) / e.context.max)}% context`);
    if (e.error) this.place(this.record<NoteRecord>('note', { level: 'error', text: e.error }));
    if (parts.length) this.place(this.record<TurnRecord>('turn', { text: parts.join(' · ') }));
    this.finish();
  }

  private ended(code: number): void {
    this.over = code;
    this.finish(true);
    this.place(this.record<OverRecord>('over', { code, runId: this.session?.run_id ?? null }));
  }
}
