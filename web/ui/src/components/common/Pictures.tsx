import type { Picture } from '../../api/types';
import { PICTURE, type PastedImages } from '../../hooks/usePastedImages';

const src = (p: Picture): string => `data:${p.type};base64,${p.data}`;

interface TrayProps {
  pictures: PastedImages;
  id?: string;
  /** After a picture was taken out again: the field gets the focus back. */
  onRemoved?: () => void;
}

/** The pictures pasted into a message not yet sent, each with a button that takes it out again. */
export function ImageTray({ pictures, id, onRemoved }: TrayProps) {
  return (
    <div className="shots" id={id}>
      {pictures.held.map((p, k) => (
        <span className="shot" key={k}>
          {PICTURE.test(p.type) ? <img src={src(p)} alt="Pasted image" /> : <span className="file">{p.name}</span>}
          <button type="button" aria-label={PICTURE.test(p.type) ? 'Remove image' : 'Remove file'} title="Remove" onClick={() => { pictures.drop(p); onRemoved?.(); }}>
            ✕
          </button>
        </span>
      ))}
    </div>
  );
}

/** The pictures and the names of the files of a message that was sent, as it shows them. */
export function SentImages({ images = [], files = [] }: { images?: Picture[]; files?: string[] }) {
  return (
    <div className="shots">
      {images.filter(p => PICTURE.test(p.type) && /^[A-Za-z0-9+/=]+$/.test(p.data)).map((p, k) => (
        <img key={k} src={src(p)} alt="Image" />
      ))}
      {files.map((name, k) => <span className="file" key={'f' + k}>{name}</span>)}
    </div>
  );
}
