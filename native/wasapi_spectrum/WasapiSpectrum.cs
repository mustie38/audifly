// Audifly Native WASAPI Loopback + Real-Time Radix-2 FFT Spectrum Analyzer
// Zero external dependencies — compiles directly with Windows built-in csc.exe (.NET 4.x).
//
// Usage:
//   WasapiSpectrum.exe [--bands 32] [--fps 30]
//   WasapiSpectrum.exe --self-test
//
// Captures the default Windows audio output (speakers/headphones) via WASAPI loopback
// without requiring microphone permission, computes a 1024-point Hann-windowed FFT,
// and streams normalized logarithmic frequency bands (0.000..1.000) to stdout.

using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace Audifly.NativeSpectrum
{
    internal static class Program
    {
        private const int FftSize = 1024;
        private const uint AudclntStreamflagsLoopback = 0x00020000;
        private const uint AudclntBufferflagsSilent = 0x2;
        private const int S_OK = 0;
        private const int AudclntSBufferEmpty = 0x08890001;
        private const ushort WaveFormatPcm = 1;
        private const ushort WaveFormatIeeeFloat = 3;
        private const ushort WaveFormatExtensible = 0xFFFE;

        private static readonly Guid KsdDataFormatSubtypeIeeeFloat =
            new Guid("00000003-0000-0010-8000-00aa00389b71");
        private static readonly Guid KsdDataFormatSubtypePcm =
            new Guid("00000001-0000-0010-8000-00aa00389b71");

        private static volatile bool _running = true;

        [MTAThread]
        public static int Main(string[] args)
        {
            int bandCount = 32;
            int fps = 30;
            bool selfTest = false;

            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--self-test")
                {
                    selfTest = true;
                }
                else if (args[i] == "--bands" && i + 1 < args.Length)
                {
                    int v;
                    if (int.TryParse(args[++i], out v)) bandCount = Math.Max(8, Math.Min(64, v));
                }
                else if (args[i] == "--fps" && i + 1 < args.Length)
                {
                    int v;
                    if (int.TryParse(args[++i], out v)) fps = Math.Max(10, Math.Min(60, v));
                }
            }

            if (selfTest)
            {
                return RunSelfTest(bandCount);
            }

            // Watch stdin so we exit cleanly if parent Python process exits or closes pipe.
            Thread stdinWatcher = new Thread(() =>
            {
                try
                {
                    string line;
                    while ((line = Console.ReadLine()) != null)
                    {
                        if (line.Trim().Equals("quit", StringComparison.OrdinalIgnoreCase))
                        {
                            _running = false;
                            break;
                        }
                    }
                }
                catch
                {
                }
                _running = false;
            });
            stdinWatcher.IsBackground = true;
            stdinWatcher.Start();

            Console.CancelKeyPress += (s, e) =>
            {
                e.Cancel = true;
                _running = false;
            };

            try
            {
                RunLoopbackCapture(bandCount, fps);
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("WASAPI_ERR: " + ex.Message);
                return 1;
            }
        }

        private static int RunSelfTest(int bandCount)
        {
            const int sampleRate = 48000;
            float[] ring = new float[FftSize];
            for (int i = 0; i < FftSize; i++)
            {
                double t = (double)i / sampleRate;
                ring[i] = (float)(0.6 * Math.Sin(2.0 * Math.PI * 180.0 * t)
                                + 0.4 * Math.Sin(2.0 * Math.PI * 2400.0 * t));
            }
            double[] hann = BuildHannWindow(FftSize);
            double[] re = new double[FftSize];
            double[] im = new double[FftSize];
            double[] bands = new double[bandCount];

            ComputeBands(ring, 0, hann, re, im, sampleRate, bands);

            double maxVal = 0.0;
            int maxIdx = -1;
            for (int i = 0; i < bandCount; i++)
            {
                if (bands[i] > maxVal)
                {
                    maxVal = bands[i];
                    maxIdx = i;
                }
            }
            if (maxVal < 0.25 || maxIdx < 0)
            {
                Console.Error.WriteLine("SELF_TEST_FAIL: peak too low (" + maxVal.ToString("F3", CultureInfo.InvariantCulture) + ")");
                return 2;
            }
            Console.WriteLine("SELF_TEST_OK bands=" + bandCount + " peak_idx=" + maxIdx + " peak=" + maxVal.ToString("F3", CultureInfo.InvariantCulture));
            return 0;
        }

        private static void RunLoopbackCapture(int bandCount, int fps)
        {
            var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
            IMMDevice device;
            Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(0, 0, out device)); // eRender, eConsole

            Guid iidAudioClient = typeof(IAudioClient).GUID;
            object audioClientObj;
            Marshal.ThrowExceptionForHR(device.Activate(ref iidAudioClient, 0x17, IntPtr.Zero, out audioClientObj));
            var audioClient = (IAudioClient)audioClientObj;

            IntPtr mixFormatPtr;
            Marshal.ThrowExceptionForHR(audioClient.GetMixFormat(out mixFormatPtr));
            WaveFormatInfo fmt;
            try
            {
                fmt = ParseWaveFormat(mixFormatPtr);
                // Initialize shared loopback mode with 100ms buffer (1,000,000 in 100ns units)
                Marshal.ThrowExceptionForHR(audioClient.Initialize(
                    0, // AUDCLNT_SHAREMODE_SHARED
                    AudclntStreamflagsLoopback,
                    1000000,
                    0,
                    mixFormatPtr,
                    IntPtr.Zero));
            }
            finally
            {
                Marshal.FreeCoTaskMem(mixFormatPtr);
            }

            Guid iidCapture = typeof(IAudioCaptureClient).GUID;
            object captureObj;
            Marshal.ThrowExceptionForHR(audioClient.GetService(ref iidCapture, out captureObj));
            var captureClient = (IAudioCaptureClient)captureObj;

            Marshal.ThrowExceptionForHR(audioClient.Start());

            float[] ring = new float[FftSize];
            int ringPos = 0;
            double[] hann = BuildHannWindow(FftSize);
            double[] re = new double[FftSize];
            double[] im = new double[FftSize];
            double[] bands = new double[bandCount];
            double[] smooth = new double[bandCount];

            int frameIntervalMs = Math.Max(16, 1000 / fps);
            var sb = new StringBuilder(bandCount * 7);
            long lastEmitTick = Environment.TickCount;

            try
            {
                while (_running)
                {
                    uint packetFrames;
                    int hr = captureClient.GetNextPacketSize(out packetFrames);
                    if (hr != S_OK) break;

                    bool gotAudio = false;
                    while (packetFrames > 0 && _running)
                    {
                        IntPtr dataPtr;
                        uint numFrames;
                        uint flags;
                        ulong devPos, qpcPos;

                        hr = captureClient.GetBuffer(out dataPtr, out numFrames, out flags, out devPos, out qpcPos);
                        if (hr == AudclntSBufferEmpty) break;
                        if (hr != S_OK) break;

                        try
                        {
                            bool isSilent = (flags & AudclntBufferflagsSilent) != 0;
                            if (isSilent || dataPtr == IntPtr.Zero)
                            {
                                for (uint f = 0; f < numFrames; f++)
                                {
                                    ring[ringPos] = 0f;
                                    ringPos = (ringPos + 1) & (FftSize - 1);
                                }
                            }
                            else
                            {
                                gotAudio = true;
                                ReadSamplesIntoRing(dataPtr, (int)numFrames, fmt, ring, ref ringPos);
                            }
                        }
                        finally
                        {
                            captureClient.ReleaseBuffer(numFrames);
                        }

                        hr = captureClient.GetNextPacketSize(out packetFrames);
                        if (hr != S_OK) break;
                    }

                    long now = Environment.TickCount;
                    if (unchecked(now - lastEmitTick) >= frameIntervalMs)
                    {
                        lastEmitTick = now;

                        if (!gotAudio)
                        {
                            // Decay ring gently if Windows paused packet delivery during silence
                            for (int i = 0; i < FftSize; i++) ring[i] *= 0.80f;
                        }

                        ComputeBands(ring, ringPos, hann, re, im, fmt.SampleRate, bands);

                        sb.Clear();
                        for (int b = 0; b < bandCount; b++)
                        {
                            double target = bands[b];
                            // Snappy attack, smooth decay
                            double alpha = target > smooth[b] ? 0.58 : 0.28;
                            smooth[b] = smooth[b] + (target - smooth[b]) * alpha;
                            if (smooth[b] < 0.002) smooth[b] = 0.0;
                            if (b > 0) sb.Append(',');
                            sb.Append(smooth[b].ToString("0.000", CultureInfo.InvariantCulture));
                        }
                        Console.WriteLine(sb.ToString());
                        Console.Out.Flush();
                    }

                    Thread.Sleep(8);
                }
            }
            finally
            {
                try { audioClient.Stop(); } catch { }
                Marshal.ReleaseComObject(captureClient);
                Marshal.ReleaseComObject(audioClient);
                Marshal.ReleaseComObject(device);
                Marshal.ReleaseComObject(enumerator);
            }
        }

        private struct WaveFormatInfo
        {
            public int Channels;
            public int SampleRate;
            public int BitsPerSample;
            public bool IsFloat;
        }

        private static WaveFormatInfo ParseWaveFormat(IntPtr ptr)
        {
            ushort tag = (ushort)Marshal.ReadInt16(ptr, 0);
            ushort channels = (ushort)Marshal.ReadInt16(ptr, 2);
            int sampleRate = Marshal.ReadInt32(ptr, 4);
            ushort bits = (ushort)Marshal.ReadInt16(ptr, 14);
            bool isFloat = (tag == WaveFormatIeeeFloat);

            if (tag == WaveFormatExtensible)
            {
                byte[] guidBytes = new byte[16];
                Marshal.Copy(IntPtr.Add(ptr, 24), guidBytes, 0, 16);
                Guid subFormat = new Guid(guidBytes);
                if (subFormat == KsdDataFormatSubtypeIeeeFloat) isFloat = true;
                else if (subFormat == KsdDataFormatSubtypePcm) isFloat = false;
            }

            return new WaveFormatInfo
            {
                Channels = Math.Max(1, (int)channels),
                SampleRate = Math.Max(8000, sampleRate),
                BitsPerSample = bits,
                IsFloat = isFloat
            };
        }

        private static void ReadSamplesIntoRing(
            IntPtr dataPtr, int numFrames, WaveFormatInfo fmt, float[] ring, ref int ringPos)
        {
            int ch = fmt.Channels;
            if (fmt.IsFloat && fmt.BitsPerSample == 32)
            {
                int totalFloats = numFrames * ch;
                float[] buf = new float[totalFloats];
                Marshal.Copy(dataPtr, buf, 0, totalFloats);
                float invCh = 1.0f / ch;
                for (int f = 0; f < numFrames; f++)
                {
                    float sum = 0f;
                    int offset = f * ch;
                    for (int c = 0; c < ch; c++) sum += buf[offset + c];
                    ring[ringPos] = sum * invCh;
                    ringPos = (ringPos + 1) & (FftSize - 1);
                }
            }
            else if (!fmt.IsFloat && fmt.BitsPerSample == 16)
            {
                int totalShorts = numFrames * ch;
                short[] buf = new short[totalShorts];
                Marshal.Copy(dataPtr, buf, 0, totalShorts);
                float inv = 1.0f / (32768.0f * ch);
                for (int f = 0; f < numFrames; f++)
                {
                    float sum = 0f;
                    int offset = f * ch;
                    for (int c = 0; c < ch; c++) sum += buf[offset + c];
                    ring[ringPos] = sum * inv;
                    ringPos = (ringPos + 1) & (FftSize - 1);
                }
            }
        }

        private static double[] BuildHannWindow(int n)
        {
            double[] w = new double[n];
            for (int i = 0; i < n; i++)
                w[i] = 0.5 * (1.0 - Math.Cos(2.0 * Math.PI * i / (n - 1)));
            return w;
        }

        private static void ComputeBands(
            float[] ring, int ringPos, double[] hann,
            double[] re, double[] im, int sampleRate, double[] outBands)
        {
            for (int i = 0; i < FftSize; i++)
            {
                int idx = (ringPos + i) & (FftSize - 1);
                re[i] = ring[idx] * hann[i];
                im[i] = 0.0;
            }

            FftRadix2(re, im);

            int half = FftSize / 2;
            double minFreq = 45.0;
            double maxFreq = Math.Min(16000.0, sampleRate * 0.45);
            double logMin = Math.Log(minFreq);
            double logMax = Math.Log(maxFreq);
            int bandCount = outBands.Length;

            for (int b = 0; b < bandCount; b++)
            {
                double f0 = Math.Exp(logMin + (logMax - logMin) * b / bandCount);
                double f1 = Math.Exp(logMin + (logMax - logMin) * (b + 1) / bandCount);
                int bin0 = Math.Max(1, (int)Math.Floor(f0 * FftSize / sampleRate));
                int bin1 = Math.Min(half - 1, Math.Max(bin0, (int)Math.Ceiling(f1 * FftSize / sampleRate)));

                double sumSq = 0.0;
                int cnt = 0;
                for (int k = bin0; k <= bin1; k++)
                {
                    double mag = Math.Sqrt(re[k] * re[k] + im[k] * im[k]) / (FftSize * 0.5);
                    sumSq += mag * mag;
                    cnt++;
                }
                double rms = cnt > 0 ? Math.Sqrt(sumSq / cnt) : 0.0;
                // Convert RMS magnitude to perceptual dB scale (-58 dB .. -6 dB -> 0.0 .. 1.0)
                double db = 20.0 * Math.Log10(rms + 1e-7);
                // Slight treble tilt so high frequencies look lively like a hardware analyzer
                double tilt = 1.0 + (double)b / bandCount * 0.25;
                double norm = ((db + 58.0) / 52.0) * tilt;
                if (norm < 0.0) norm = 0.0;
                if (norm > 1.0) norm = 1.0;
                outBands[b] = norm;
            }
        }

        private static void FftRadix2(double[] re, double[] im)
        {
            int n = re.Length;
            // Bit-reversal permutation
            for (int i = 1, j = 0; i < n; i++)
            {
                int bit = n >> 1;
                for (; (j & bit) != 0; bit >>= 1) j ^= bit;
                j ^= bit;
                if (i < j)
                {
                    double tr = re[i]; re[i] = re[j]; re[j] = tr;
                    double ti = im[i]; im[i] = im[j]; im[j] = ti;
                }
            }
            // Cooley-Tukey butterfly stages
            for (int len = 2; len <= n; len <<= 1)
            {
                double ang = -2.0 * Math.PI / len;
                double wlenRe = Math.Cos(ang);
                double wlenIm = Math.Sin(ang);
                int halfLen = len >> 1;
                for (int i = 0; i < n; i += len)
                {
                    double wRe = 1.0, wIm = 0.0;
                    for (int j = 0; j < halfLen; j++)
                    {
                        int u = i + j;
                        int v = u + halfLen;
                        double vRe = re[v] * wRe - im[v] * wIm;
                        double vIm = re[v] * wIm + im[v] * wRe;
                        re[v] = re[u] - vRe;
                        im[v] = im[u] - vIm;
                        re[u] += vRe;
                        im[u] += vIm;
                        double nextWRe = wRe * wlenRe - wIm * wlenIm;
                        wIm = wRe * wlenIm + wIm * wlenRe;
                        wRe = nextWRe;
                    }
                }
            }
        }

        // ---- Minimal Windows Core Audio COM Interop ----

        [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
        private class MMDeviceEnumeratorComObject { }

        [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IMMDeviceEnumerator
        {
            int EnumAudioEndpoints(int dataFlow, int stateMask, out IntPtr devices);
            [PreserveSig]
            int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
        }

        [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IMMDevice
        {
            [PreserveSig]
            int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object iface);
        }

        [Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IAudioClient
        {
            [PreserveSig]
            int Initialize(int shareMode, uint streamFlags, long hnsBufferDuration, long hnsPeriodicity, IntPtr format, IntPtr audioSessionGuid);
            [PreserveSig]
            int GetBufferSize(out uint numBufferFrames);
            [PreserveSig]
            int GetStreamLatency(out long latency);
            [PreserveSig]
            int GetCurrentPadding(out uint numPaddingFrames);
            [PreserveSig]
            int IsFormatSupported(int shareMode, IntPtr format, out IntPtr closestMatch);
            [PreserveSig]
            int GetMixFormat(out IntPtr deviceFormatPointer);
            [PreserveSig]
            int GetDevicePeriod(out long defaultDevicePeriod, out long minimumDevicePeriod);
            [PreserveSig]
            int Start();
            [PreserveSig]
            int Stop();
            [PreserveSig]
            int Reset();
            [PreserveSig]
            int SetEventHandle(IntPtr eventHandle);
            [PreserveSig]
            int GetService(ref Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object ppv);
        }

        [Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IAudioCaptureClient
        {
            [PreserveSig]
            int GetBuffer(out IntPtr data, out uint numFramesAvailable, out uint flags, out ulong devicePosition, out ulong qpcPosition);
            [PreserveSig]
            int ReleaseBuffer(uint numFramesRead);
            [PreserveSig]
            int GetNextPacketSize(out uint numFramesInNextPacket);
        }
    }
}
