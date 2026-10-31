// Known placeholder/camera-icon filenames the ingestion pipeline inserts for slides whose image
// it couldn't extract. Filtered out of question/answer image thumbnails across the Knowledge
// Base page so quizmasters never see a broken-camera icon mistaken for real slide content.
// Brittle by nature -- a hardcoded filename list will miss placeholders from a different deck
// template (QShala priority plan P3-1 flagged this; left as-is here, just relocated out of the
// page component so QuestionFormatDisplay and the row renderer share one copy instead of two).
const PLACEHOLDER_ICONS = new Set([
  'slide_41_img_1.png', 'slide_40_img_1.png', 'slide_49_img_1.png',
  'slide_53_img_1.png', 'slide_120_img_1.png', 'slide_122_img_1.png',
  'image16.png',
]);

export function isPlaceholderIcon(url?: string | null): boolean {
  if (!url) return false;
  const name = url.replace(/\\/g, '/').split('/').pop()?.toLowerCase();
  return name ? PLACEHOLDER_ICONS.has(name) : false;
}
