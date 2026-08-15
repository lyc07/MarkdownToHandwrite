`sdt_trajectories.zip` contains the 6763 per-character `.npy` trajectories generated
from the samplechar-tuned SDT checkpoint. Entries are named by lowercase Unicode
code point (for example, `4e00.npy`). The runtime reads entries directly from the
archive and does not require the SDT training repository or PyTorch.
