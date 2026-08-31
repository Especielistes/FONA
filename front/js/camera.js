export async function startCamera(video) {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: {
      width: { ideal: 640 },
      height: { ideal: 480 },
      facingMode: "user",
    },
    audio: false,
  });

  video.srcObject = stream;
  await video.play();

  return stream;
}

export function stopCamera(stream) {
  if (!stream) {
    return;
  }

  for (const track of stream.getTracks()) {
    track.stop();
  }
}

export async function createMicrophone(onPCM) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
    video: false,
  });

  const AudioContextClass =
    window.AudioContext || window.webkitAudioContext;

  const audioContext = new AudioContextClass();

  await audioContext.resume();

  const source = audioContext.createMediaStreamSource(stream);

  const processor = audioContext.createScriptProcessor(
    4096,
    1,
    1
  );

  const gain = audioContext.createGain();
  gain.gain.value = 0;

  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0);

    const pcm = downsampleTo16k(
      input,
      audioContext.sampleRate
    );

    if (pcm.length) {
      onPCM(pcm.buffer);
    }
  };

  source.connect(processor);
  processor.connect(gain);
  gain.connect(audioContext.destination);

  return {
    stream,

    async stop() {
      processor.disconnect();
      source.disconnect();
      gain.disconnect();

      for (const track of stream.getTracks()) {
        track.stop();
      }

      await audioContext.close();
    },
  };
}

function downsampleTo16k(input, inputSampleRate) {
  const targetRate = 16000;

  if (inputSampleRate === targetRate) {
    return floatTo16BitPCM(input);
  }

  const ratio = inputSampleRate / targetRate;
  const outputLength = Math.floor(input.length / ratio);
  const output = new Int16Array(outputLength);

  let inputIndex = 0;

  for (let i = 0; i < outputLength; i++) {
    const nextInputIndex = Math.floor((i + 1) * ratio);

    let sum = 0;
    let count = 0;

    while (
      inputIndex < nextInputIndex &&
      inputIndex < input.length
    ) {
      sum += input[inputIndex];
      count++;
      inputIndex++;
    }

    const sample = count ? sum / count : 0;

    output[i] = Math.max(
      -32768,
      Math.min(32767, Math.round(sample * 32767))
    );
  }

  return output;
}

function floatTo16BitPCM(input) {
  const output = new Int16Array(input.length);

  for (let i = 0; i < input.length; i++) {
    const sample = Math.max(-1, Math.min(1, input[i]));

    output[i] =
      sample < 0
        ? sample * 32768
        : sample * 32767;
  }

  return output;
}