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
          <img src={src(p)} alt="Pasted image" />
          <button type="button" aria-label="Remove image" title="Remove" onClick={() => { pictures.drop(p); onRemoved?.(); }}>
            ✕
          </button>
        </span>
      ))}
    </div>
  );
}

/** The pictures of a message that was sent, as it shows them. */
export function SentImages({ images }: { images: Picture[] }) {
  return (
    <div className="shots">
      {images.filter(p => PICTURE.test(p.type) && /^[A-Za-z0-9+/=]+$/.test(p.data)).map((p, k) => (
        <img key={k} src={src(p)} alt="Image" />
      ))}
    </div>
  );
}
