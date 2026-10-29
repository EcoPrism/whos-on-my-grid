// The what-if page's one standing sentence: nothing on it happened. Sticky so
// it is on screen beside every number, in the modelled colour the numbers
// carry. The text is the scenario's own `disclosure`, so the page, the share
// card and the PNG say the same thing.
export default function HypotheticalBanner({ text }: { text: string }) {
  return (
    <div role="note" aria-label="About this page" className="banner-modelled sticky top-0 z-[1100]">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2">
        <span aria-hidden className="banner-mark wide shrink-0 px-1.5 text-xs font-bold uppercase tracking-wide">
          What-if
        </span>
        <p className="text-[15px] font-semibold leading-snug">{text}</p>
      </div>
    </div>
  )
}
