/**
 * Keep the user's own video across a page reload, without ever uploading it.
 *
 * On the browser-tracking path the server never receives the video, only landmarks and a handful
 * of small frames. `localVideo.ts` holds the file in a module-level map, which survives
 * client-side navigation from upload to report but dies on reload - and the report then falls back
 * to `/jobs/{id}/video`, which does not exist on that path. So a reload left the annotated player
 * with a 404 for a source: the analysis was intact and the evidence it was drawn on vanished.
 *
 * IndexedDB rather than sessionStorage because these are blobs of up to 200 MB and
 * sessionStorage only takes strings, at a few megabytes. Everything here fails soft: storage can
 * be unavailable (private browsing), full, or refused, and none of that is allowed to break a
 * report that is already on screen.
 */

const DB_NAME = "squat-coach";
const DB_VERSION = 1;
const STORE = "videos";

// How many recent videos to keep. These are large; without eviction a demo session of a dozen
// uploads would sit on several gigabytes of the user's disk indefinitely.
const KEEP_NEWEST = 3;

type Row = { jobId: string; blob: Blob; savedAt: number };

function open(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    if (typeof indexedDB === "undefined") return resolve(null);
    let req: IDBOpenDBRequest;
    try {
      req = indexedDB.open(DB_NAME, DB_VERSION);
    } catch {
      return resolve(null);
    }
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "jobId" }).createIndex("savedAt", "savedAt");
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => resolve(null);
    req.onblocked = () => resolve(null);
  });
}

function done(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve) => {
    tx.oncomplete = () => resolve();
    // A quota failure lands here. Resolve rather than reject: the caller cannot do anything
    // useful about it and the report is already rendered from the in-memory copy.
    tx.onerror = () => resolve();
    tx.onabort = () => resolve();
  });
}

export async function putVideo(jobId: string, blob: Blob): Promise<void> {
  const db = await open();
  if (!db) return;
  try {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    store.put({ jobId, blob, savedAt: Date.now() } satisfies Row);
    await done(tx);
    await evict(db);
  } catch {
    /* storage unavailable or full; the in-memory copy still works this session */
  } finally {
    db.close();
  }
}

export async function getVideo(jobId: string): Promise<Blob | null> {
  const db = await open();
  if (!db) return null;
  try {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).get(jobId);
    await done(tx);
    const row = req.result as Row | undefined;
    return row?.blob ?? null;
  } catch {
    return null;
  } finally {
    db.close();
  }
}

async function evict(db: IDBDatabase): Promise<void> {
  try {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    const req = store.getAll();
    await done(tx);
    const rows = ((req.result as Row[]) ?? []).sort((a, b) => b.savedAt - a.savedAt);
    const stale = rows.slice(KEEP_NEWEST);
    if (!stale.length) return;
    const tx2 = db.transaction(STORE, "readwrite");
    const s2 = tx2.objectStore(STORE);
    for (const r of stale) s2.delete(r.jobId);
    await done(tx2);
  } catch {
    /* eviction is housekeeping, never worth surfacing */
  }
}
