import { HandLandmarker, FilesetResolver } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";

const K = 5;
const SMOOTHING_FRAMES = 4;
const SMOOTHING_REQUIRED = 2;
const SIGN_COOLDOWN_MS = 1000; // Cooldown entre detección de la misma palabra
const DISTANCE_THRESHOLD = 1.85; // Umbral óptimo verificado (distancia media de misma clase = 1.30)

const CONNECTIONS = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];

export class SignRecognizer {
  constructor({ video, overlay, onSign, onStatus }) {
    this.video = video;
    this.overlay = overlay;
    this.ctx = overlay ? overlay.getContext("2d") : null;
    this.onSign = onSign;
    this.onStatus = onStatus;

    this.singleHandTemplates = []; // [{ label, vec }] (63 floats)
    this.twoHandTemplates = [];   // [{ label, vec }] (126 floats)
    this.landmarker = null;
    this.running = false;
    this.shouldRun = false;
    this.voteBuffer = [];
    this.lastVideoTime = -1;
    this.lastDetectedSign = null;
    this.lastDetectedTime = 0;
    this.animFrameId = null;
  }

  async init() {
    try {
      this.onStatus?.("Cargando modelo de signos…");

      // Cargar dataset de signos pregrabados
      const response = await fetch("../data/gestures.json");
      if (response.ok) {
        const payload = await response.json();
        for (const [label, samples] of Object.entries(payload.gestures || {})) {
          for (const s of samples) {
            const hasR = s[126];
            const hasL = s[127];
            if (hasR === 1 && hasL === 0) {
              this.singleHandTemplates.push({ label, vec: s.slice(0, 63) });
            } else if (hasR === 0 && hasL === 1) {
              this.singleHandTemplates.push({ label, vec: s.slice(63, 126) });
            } else if (hasR === 1 && hasL === 1) {
              this.twoHandTemplates.push({ label, vec: s.slice(0, 126) });
            }
          }
        }
      }

      // Cargar MediaPipe Vision Tasks
      const vision = await FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
      );

      this.landmarker = await HandLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
          delegate: "GPU",
        },
        runningMode: "VIDEO",
        numHands: 2,
        minHandDetectionConfidence: 0.5,
        minTrackingConfidence: 0.5,
      });

      this.onStatus?.("Detector de signos listo");
      if (this.shouldRun) {
        this.start();
      }
      return true;
    } catch (error) {
      console.warn("MediaPipe no disponible:", error);
      this.onStatus?.("Modo signos disponible (manual)");
      return false;
    }
  }

  start() {
    this.shouldRun = true;
    if (!this.landmarker || this.running) return;
    this.running = true;
    this.loop();
  }

  stop() {
    this.shouldRun = false;
    this.running = false;
    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
    if (this.ctx && this.overlay) {
      this.ctx.clearRect(0, 0, this.overlay.width, this.overlay.height);
    }
    this.voteBuffer = [];
  }

  normalizeHand(landmarks) {
    const wrist = landmarks[0];
    const relative = [];
    let maxNorm = 0;

    for (const point of landmarks) {
      const x = point.x - wrist.x;
      const y = point.y - wrist.y;
      const z = point.z - wrist.z;
      relative.push([x, y, z]);
      const norm = Math.hypot(x, y, z);
      if (norm > maxNorm) maxNorm = norm;
    }

    if (maxNorm === 0) maxNorm = 1;

    const flat = [];
    for (const [x, y, z] of relative) {
      flat.push(x / maxNorm, y / maxNorm, z / maxNorm);
    }
    return flat; // 63 valores
  }

  distance(a, b) {
    let sum = 0;
    const len = Math.min(a.length, b.length);
    for (let i = 0; i < len; i++) {
      const diff = a[i] - b[i];
      sum += diff * diff;
    }
    return Math.sqrt(sum);
  }

  flipX(vec63) {
    const flipped = new Array(63);
    for (let i = 0; i < 63; i++) {
      flipped[i] = i % 3 === 0 ? -vec63[i] : vec63[i];
    }
    return flipped;
  }

  classify(result) {
    const numHands = result.landmarks.length;
    if (numHands === 0) return null;

    if (numHands === 1) {
      const handNorm = this.normalizeHand(result.landmarks[0]);
      const handFlipped = this.flipX(handNorm);

      const neighbours = [];
      for (const t of this.singleHandTemplates) {
        const d1 = this.distance(handNorm, t.vec);
        const d2 = this.distance(handFlipped, t.vec);
        neighbours.push({ label: t.label, dist: Math.min(d1, d2) });
      }

      if (neighbours.length === 0) return null;
      neighbours.sort((a, b) => a.dist - b.dist);
      const top = neighbours.slice(0, K);

      const votes = new Map();
      for (const item of top) {
        votes.set(item.label, (votes.get(item.label) || 0) + 1);
      }

      let best = null;
      let bestVotes = 0;
      for (const [label, count] of votes) {
        if (count > bestVotes) {
          best = label;
          bestVotes = count;
        }
      }

      const matching = top.filter((item) => item.label === best);
      const meanDist = matching.reduce((acc, item) => acc + item.dist, 0) / matching.length;

      return { label: best, dist: meanDist, accepted: meanDist <= DISTANCE_THRESHOLD };
    }

    if (numHands >= 2) {
      const hand0 = this.normalizeHand(result.landmarks[0]);
      const hand1 = this.normalizeHand(result.landmarks[1]);
      const vecA = [...hand0, ...hand1];
      const vecB = [...hand1, ...hand0];

      const neighbours = [];
      for (const t of this.twoHandTemplates) {
        const d1 = this.distance(vecA, t.vec);
        const d2 = this.distance(vecB, t.vec);
        neighbours.push({ label: t.label, dist: Math.min(d1, d2) });
      }

      if (neighbours.length === 0) return null;
      neighbours.sort((a, b) => a.dist - b.dist);
      const top = neighbours.slice(0, K);

      const votes = new Map();
      for (const item of top) {
        votes.set(item.label, (votes.get(item.label) || 0) + 1);
      }

      let best = null;
      let bestVotes = 0;
      for (const [label, count] of votes) {
        if (count > bestVotes) {
          best = label;
          bestVotes = count;
        }
      }

      const matching = top.filter((item) => item.label === best);
      const meanDist = matching.reduce((acc, item) => acc + item.dist, 0) / matching.length;

      return { label: best, dist: meanDist, accepted: meanDist <= (DISTANCE_THRESHOLD * 1.3) };
    }

    return null;
  }

  smoothPrediction(result) {
    this.voteBuffer.push(result ? (result.accepted ? result.label : null) : null);
    if (this.voteBuffer.length > SMOOTHING_FRAMES) this.voteBuffer.shift();

    const counts = new Map();
    for (const vote of this.voteBuffer) {
      if (vote === null) continue;
      counts.set(vote, (counts.get(vote) || 0) + 1);
    }

    for (const [label, count] of counts) {
      if (count >= SMOOTHING_REQUIRED) return label;
    }
    return null;
  }

  draw(result) {
    if (!this.ctx || !this.overlay || !this.video) return;
    this.overlay.width = this.video.videoWidth || 640;
    this.overlay.height = this.video.videoHeight || 480;
    this.ctx.clearRect(0, 0, this.overlay.width, this.overlay.height);

    for (const landmarks of result.landmarks) {
      this.ctx.strokeStyle = "#37F0C2";
      this.ctx.lineWidth = 2.5;
      for (const [from, to] of CONNECTIONS) {
        this.ctx.beginPath();
        this.ctx.moveTo(landmarks[from].x * this.overlay.width, landmarks[from].y * this.overlay.height);
        this.ctx.lineTo(landmarks[to].x * this.overlay.width, landmarks[to].y * this.overlay.height);
        this.ctx.stroke();
      }

      this.ctx.fillStyle = "#FFFFFF";
      for (const point of landmarks) {
        this.ctx.beginPath();
        this.ctx.arc(point.x * this.overlay.width, point.y * this.overlay.height, 3.5, 0, Math.PI * 2);
        this.ctx.fill();
      }
    }
  }

  loop() {
    if (!this.running) return;

    if (this.video && this.video.readyState >= 2 && this.video.currentTime !== this.lastVideoTime) {
      this.lastVideoTime = this.video.currentTime;
      if (this.landmarker) {
        const result = this.landmarker.detectForVideo(this.video, performance.now());
        this.draw(result);

        if (result.landmarks.length > 0) {
          const guess = this.classify(result);
          const stable = this.smoothPrediction(guess);

          if (stable) {
            const now = performance.now();
            if (stable !== this.lastDetectedSign || now - this.lastDetectedTime > SIGN_COOLDOWN_MS) {
              this.lastDetectedSign = stable;
              this.lastDetectedTime = now;
              this.onSign?.(stable);
            }
          }
        } else {
          this.smoothPrediction(null);
          if (this.ctx && this.overlay) {
            this.ctx.clearRect(0, 0, this.overlay.width, this.overlay.height);
          }
        }
      }
    }

    this.animFrameId = requestAnimationFrame(() => this.loop());
  }
}