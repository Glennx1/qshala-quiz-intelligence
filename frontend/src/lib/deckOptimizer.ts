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

/**
 * Optimizes large PPTX presentation decks (> 4.5 MB) directly in the browser
 * by stripping embedded tournament video and audio files and stubbing heavy images.
 * Retains 100% of slide text, questions, choices, answers, and speaker notes.
 */
export async function optimizeDeckInBrowser(
  file: File,
  onStatusUpdate?: (status: string) => void
): Promise<File> {
  const maxAllowedBytes = 4.4 * 1024 * 1024; // 4.4 MB safe Vercel payload ceiling

  if (file.size <= maxAllowedBytes) {
    return file;
  }

  const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (ext !== '.pptx' && ext !== '.ppt') {
    return file;
  }

  const originalMb = (file.size / (1024 * 1024)).toFixed(1);
  onStatusUpdate?.(`Optimizing deck (${originalMb} MB) for Vercel...`);

  const zip = await JSZip.loadAsync(file);

  // Pass 1: Strip heavy video and audio streams completely
  for (const filename of Object.keys(zip.files)) {
    if (filename.startsWith('ppt/media/')) {
      const mediaExt = filename.substring(filename.lastIndexOf('.')).toLowerCase();
      if (HEAVY_MEDIA_EXTS.has(mediaExt)) {
        zip.file(filename, '');
      } else if (mediaExt === '.gif') {
        zip.file(filename, TINY_GIF_BASE64, { base64: true });
      }
    }
  }

  // Pass 2: Stub images > 80 KB
  for (const filename of Object.keys(zip.files)) {
    if (filename.startsWith('ppt/media/')) {
      const mediaExt = filename.substring(filename.lastIndexOf('.')).toLowerCase();
      if (IMAGE_EXTS.has(mediaExt) && mediaExt !== '.gif') {
        const entry: any = zip.files[filename];
        const uncompressedSize = entry?._data?.uncompressedSize || 0;
        if (uncompressedSize > 80 * 1024) {
          zip.file(filename, TINY_PNG_BASE64, { base64: true });
        }
      }
    }
  }

  onStatusUpdate?.('Re-packing lightweight presentation package...');

  const optimizedBlob = await zip.generateAsync({
    type: 'blob',
    compression: 'DEFLATE',
    compressionOptions: { level: 9 },
  });

  // If still above 4.4MB, stub all remaining images in ppt/media/
  if (optimizedBlob.size > maxAllowedBytes) {
    onStatusUpdate?.('Applying maximum compression for Vercel...');
    for (const filename of Object.keys(zip.files)) {
      if (filename.startsWith('ppt/media/')) {
        const mediaExt = filename.substring(filename.lastIndexOf('.')).toLowerCase();
        if (mediaExt === '.gif') {
          zip.file(filename, TINY_GIF_BASE64, { base64: true });
        } else {
          zip.file(filename, TINY_PNG_BASE64, { base64: true });
        }
      }
    }

    const finalBlob = await zip.generateAsync({
      type: 'blob',
      compression: 'DEFLATE',
      compressionOptions: { level: 9 },
    });

    return new File([finalBlob], file.name, {
      type: file.type || 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    });
  }

  return new File([optimizedBlob], file.name, {
    type: file.type || 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  });
}
