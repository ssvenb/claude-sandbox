/** Whatever is loading turns: a ring in the colour of the text around it. */
export const Spin = () => <span className="spin" />;

/** A turning ring and what is being waited for. */
export function Loading({ text = '', as: Tag = 'span' }: { text?: string; as?: 'span' | 'p' }) {
  return (
    <Tag className="loading" role="status">
      <Spin />
      {text}
    </Tag>
  );
}
