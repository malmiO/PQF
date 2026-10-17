"""Objective music descriptors for the mood rule: tempo (librosa beat tracker), mode/key
(Krumhansl-Kessler key profiles on mean chroma), loudness (ITU-R BS.1770 via pyloudnorm),
energy (RMS) and brightness (spectral centroid)."""
import sys, numpy as np, librosa, pyloudnorm as pyln
MAJ=np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
MIN=np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
NAMES=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
def key(chroma):
    c=chroma.mean(axis=1); best=None
    for i in range(12):
        for prof,m in ((MAJ,'major'),(MIN,'minor')):
            r=np.corrcoef(c,np.roll(prof,i))[0,1]
            if best is None or r>best[0]: best=(r,NAMES[i],m)
    return best
print("track,tempo_bpm,key,mode,key_corr,loudness_lufs,rms_db,centroid_hz,duration_s")
for p in sys.argv[1:]:
    y,sr=librosa.load(p,sr=22050,mono=True)
    tempo,_=librosa.beat.beat_track(y=y,sr=sr)
    ch=librosa.feature.chroma_cqt(y=y,sr=sr)
    r,k,m=key(ch)
    y44,sr44=librosa.load(p,sr=44100,mono=False)
    data=y44.T if y44.ndim>1 else y44
    lufs=pyln.Meter(sr44).integrated_loudness(data)
    rms=20*np.log10(np.sqrt(np.mean(y**2))+1e-9)
    cen=librosa.feature.spectral_centroid(y=y,sr=sr).mean()
    print(f"{p.split('/')[-1][:-4]},{float(np.atleast_1d(tempo)[0]):.1f},{k},{m},{r:.2f},{lufs:.1f},{rms:.1f},{cen:.0f},{len(y)/sr:.1f}")
