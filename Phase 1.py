import warnings
warnings.filterwarnings("ignore")        # suppress deprecation noise

import numpy as np
import matplotlib.pyplot as plt

# ── Qiskit Nature ─────────────────────────────────────────────────────────────
from qiskit_nature.second_q.drivers import PySCFDriver
from qiskit_nature.second_q.mappers import JordanWignerMapper
from qiskit_nature.second_q.circuit.library import HartreeFock, UCCSD

# ── Qiskit Algorithms ─────────────────────────────────────────────────────────
from qiskit_algorithms import VQE
from qiskit_algorithms.optimizers import SLSQP
from qiskit.primitives import StatevectorEstimator   # noiseless statevector sim

# ── PySCF (classical FCI reference) ──────────────────────────────────────────
from pyscf import gto, scf, fci as pyscf_fci


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
BASIS          = "sto-3g"          # minimal basis — 2 spatial orbitals, 4 qubits
BOND_LENGTHS   = np.arange(0.5, 2.55, 0.1)   # H–H distance in Ångströms
CHEM_ACC_mEh   = 1.594                         # chemical accuracy in milli-Hartree

# ─────────────────────────────────────────────────────────────────────────────
#  SHARED OBJECTS (built once, reused at each geometry)
# ─────────────────────────────────────────────────────────────────────────────
mapper    = JordanWignerMapper()          # fermion → qubit operator mapping
estimator = StatevectorEstimator()        # exact (noise-free) expectation values
optimizer = SLSQP(maxiter=150)            # gradient-based classical optimizer


def compute_vqe_energy(atom_str: str) -> float:
    """
    Run VQE for a single H2 geometry.

    Parameters
    ----------
    atom_str : str
        PySCF atom string, e.g. 'H 0 0 0; H 0 0 0.74'

    Returns
    -------
    float
        Total VQE energy in Hartree (electronic + nuclear repulsion).
    """
    # 1. Build the electronic structure problem
    driver  = PySCFDriver(atom=atom_str, basis=BASIS)
    problem = driver.run()

    # 2. Map the fermionic Hamiltonian to a qubit operator
    #    problem.second_q_ops()[0]  →  ElectronicIntegrals → FermionicOp
    qubit_op = mapper.map(problem.second_q_ops()[0])

    # 3. Hartree–Fock reference state (classical starting point)
    hf_state = HartreeFock(
        num_spatial_orbitals=problem.num_spatial_orbitals,
        num_particles=problem.num_particles,
        qubit_mapper=mapper,
    )

    # 4. UCCSD ansatz (Unitary Coupled Cluster Singles & Doubles)
    #    Starts from |HF⟩ and adds parametrised single/double excitations
    ansatz = UCCSD(
        num_spatial_orbitals=problem.num_spatial_orbitals,
        num_particles=problem.num_particles,
        qubit_mapper=mapper,
        initial_state=hf_state,
    )

    # 5. VQE: minimise ⟨ψ(θ)|H|ψ(θ)⟩ over ansatz parameters θ
    vqe    = VQE(estimator, ansatz, optimizer)
    result = vqe.compute_minimum_eigenvalue(qubit_op)

    # 6. Add nuclear repulsion to get the total energy
    return result.eigenvalue.real + problem.nuclear_repulsion_energy


def compute_fci_energy(atom_str: str) -> float:
    """
    Run classical Full Configuration Interaction for a single H2 geometry.

    FCI is exact within the chosen basis — the gold standard for
    benchmarking approximate methods.
    """
    mol = gto.M(atom=atom_str, basis=BASIS, verbose=0)
    mf  = scf.RHF(mol).run()                  # restricted Hartree–Fock
    return pyscf_fci.FCI(mf).kernel()[0]      # exact FCI ground-state energy


# ─────────────────────────────────────────────────────────────────────────────
#  DISSOCIATION CURVE SCAN
# ─────────────────────────────────────────────────────────────────────────────
vqe_energies = []
fci_energies = []
errors_mEh   = []

print(f"{'d (Å)':>6}  {'E_VQE (Ha)':>14}  {'E_FCI (Ha)':>14}  "
      f"{'|ΔE| (mEh)':>12}  Chem. acc?")
print("─" * 65)

for d in BOND_LENGTHS:
    atom = f"H 0 0 0; H 0 0 {d:.2f}"

    e_vqe = compute_vqe_energy(atom)
    e_fci = compute_fci_energy(atom)
    err   = abs(e_vqe - e_fci) * 1000        # convert Eh → mEh

    vqe_energies.append(e_vqe)
    fci_energies.append(e_fci)
    errors_mEh.append(err)

    flag = "✓" if err < CHEM_ACC_mEh else "✗"
    print(f"{d:6.2f}  {e_vqe:14.6f}  {e_fci:14.6f}  {err:12.4f}  {flag}")

# Summary
n_acc = sum(e < CHEM_ACC_mEh for e in errors_mEh)
print(f"\nChemical accuracy achieved at {n_acc}/{len(BOND_LENGTHS)} geometries "
      f"(threshold: {CHEM_ACC_mEh} mEh)")
print(f"Maximum error: {max(errors_mEh):.4f} mEh  "
      f"at d = {BOND_LENGTHS[np.argmax(errors_mEh)]:.2f} Å")


# ─────────────────────────────────────────────────────────────────────────────
#  PLOT
# ─────────────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(8, 8), gridspec_kw={"hspace": 0.35})

# ── Top panel: Potential energy surface ──────────────────────────────────────
ax1 = axes[0]
ax1.plot(BOND_LENGTHS, fci_energies, "k-",  lw=2.0, label="FCI (exact)")
ax1.plot(BOND_LENGTHS, vqe_energies, "ro--", lw=1.5, ms=6, label="VQE-UCCSD")
ax1.axvline(0.74, color="gray", lw=0.8, ls=":", label="Equil. d = 0.74 Å")
ax1.set_xlabel("H–H bond length (Å)", fontsize=12)
ax1.set_ylabel("Total energy (Hartree)", fontsize=12)
ax1.set_title("H₂ Dissociation Curve: VQE vs. FCI  (STO-3G basis)", fontsize=13)
ax1.legend(fontsize=10)
ax1.grid(alpha=0.3)

# ── Bottom panel: Absolute error ─────────────────────────────────────────────
ax2 = axes[1]
ax2.semilogy(BOND_LENGTHS, errors_mEh, "bs-", lw=1.5, ms=6)
ax2.axhline(CHEM_ACC_mEh, color="red", lw=1.2, ls="--",
            label=f"Chemical accuracy ({CHEM_ACC_mEh} mEh)")
ax2.set_xlabel("H–H bond length (Å)", fontsize=12)
ax2.set_ylabel("|E_VQE − E_FCI| (mEh)", fontsize=12)
ax2.set_title("VQE Error vs. FCI", fontsize=13)
ax2.legend(fontsize=10)
ax2.grid(alpha=0.3, which="both")

plt.savefig("h2_dissociation_curve.png", dpi=150, bbox_inches="tight")
plt.show()
print("\nPlot saved to h2_dissociation_curve.png")
