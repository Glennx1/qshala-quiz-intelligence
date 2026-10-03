import JSZip from 'jszip';

// 1x1 base64 transparent PNG & GIF stubs
const TINY_PNG_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
const TINY_GIF_BASE64 = 'R0lGODlhAQABAIAAAAAAAAAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==';

const HEAVY_MEDIA_EXTS = new Set([
  '.mp4', '.mov', '.avi', '.wmv', '.m4v', '.flv', '.webm',
  '.mp3', '.wav', '.m4a', '.aac', '.wma', '.ogg', '.flac'
]);

const IMAGE_EXTS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.webp', '.tiff', '.bmp'
]);

export interface OptimizationResult {
  file: File;
  originalMb: number;
  newMb: number;
  reductionPct: number;
}

/**
 * Optimizes large PPTX presentation decks (> 4.5 MB) directly in the browser
 * by stripping embedded tournament videos, audios, embedded fonts, and giant images.
 * Retains 100% of slide text, questions, choices, answers, and speaker notes.
 */
export async function optimizeDeckInBrowser(
  file: File,
  onStatusUpdate?: (status: string) => void
): Promise<OptimizationResult> {
  const maxSafeBytes = 3.5 * 1024 * 1024; // 3.5 MB target (well under Vercel's 4.5 MB ceiling)
  const originalMb = Number((file.size / (1024 * 1024)).toFixed(2));

  if (file.size <= maxSafeBytes) {
    return {
      file,
      originalMb,
      newMb: originalMb,
      reductionPct: 0,
    };
  }

  const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (ext !== '.pptx' && ext !== '.ppt') {
    return {
      file,
      originalMb,
      newMb: originalMb,
      reductionPct: 0,
    };
  }

  onStatusUpdate?.(`Optimizing deck (${originalMb} MB) in browser...`);

  const zip = await JSZip.loadAsync(file);

  // 1. Strip embedded fonts (ppt/fonts/) and revision histories (ppt/changesInfos/)
  // These often consume 4 MB - 10 MB and are not needed for NLP question extraction.
  for (const filename of Object.keys(zip.files)) {
    if (filename.startsWith('ppt/fonts/') || filename.startsWith('ppt/changesInfos/')) {
      zip.file(filename, '');
    }
  }

  // 2. Strip videos, audios, and replace heavy images with lightweight 1x1 stubs
  for (const filename of Object.keys(zip.files)) {
    if (filename.startsWith('ppt/media/')) {
      const mediaExt = filename.substring(filename.lastIndexOf('.')).toLowerCase();
      if (HEAVY_MEDIA_EXTS.has(mediaExt)) {
        zip.file(filename, '');
      } else if (mediaExt === '.gif') {
        zip.file(filename, TINY_GIF_BASE64, { base64: true });
      } else if (IMAGE_EXTS.has(mediaExt)) {
        zip.file(filename, TINY_PNG_BASE64, { base64: true });
      } else {
        zip.file(filename, '');
      }
    }
  }

  onStatusUpdate?.('Packing lightweight presentation (< 2 MB)...');

  const optimizedBlob = await zip.generateAsync({
    type: 'blob',
    compression: 'DEFLATE',
    compressionOptions: { level: 9 },
  });

  const newSize = optimizedBlob.size;
  const newMb = Number((newSize / (1024 * 1024)).toFixed(2));
  const reductionPct = Number(((1 - newSize / file.size) * 100).toFixed(1));

  const optimizedFile = new File([optimizedBlob], file.name, {
    type: file.type || 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  });

  return {
    file: optimizedFile,
    originalMb,
    newMb,
    reductionPct,
  };
}
