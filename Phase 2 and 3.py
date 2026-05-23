"""
H₂ Dissociation Curve — Phase 2 & 3: Noisy VQE + Zero-Noise Extrapolation (ZNE)
==================================================================================
Builds on Phase 1 (ideal VQE baseline) by adding:

  Phase 2 — Algorithm Degradation:
    VQE under a realistic IBM-like noise model (Aer simulator).
    Noise sources: thermal relaxation (T1/T2) + depolarizing errors on gates.
    Result: the energy curve drifts upward; chemical accuracy is lost.

  Phase 3 — Recovery via ZNE:
    Zero-Noise Extrapolation using two-qubit gate folding.
    CX gates are folded at scale factors λ ∈ {1, 3, 5}.
    A quadratic fit extrapolates the trend back to λ = 0 (zero noise).
    Result: the mitigated curve is pulled significantly back toward FCI.

Noise model (IBM Eagle-like, mild settings for clear demonstration):
  T1 = T2 = 200 µs
  Single-qubit depolarizing error:   p₁ = 1×10⁻⁴
  Two-qubit (CX) depolarizing error: p₂ = 1×10⁻³

Libraries required:
    pip install qiskit qiskit-nature qiskit-algorithms qiskit-aer pyscf matplotlib
"""

import warnings
warnings.filterwarnings("ignore")

import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── Qiskit ────────────────────────────────────────────────────────────────────
from qiskit import transpile, QuantumCircuit
from qiskit.primitives import StatevectorEstimator

# ── Qiskit Nature ─────────────────────────────────────────────────────────────
from qiskit_nature.second_q.drivers import PySCFDriver
from qiskit_nature.second_q.mappers import JordanWignerMapper
from qiskit_nature.second_q.circuit.library import HartreeFock, UCCSD

# ── Qiskit Aer ────────────────────────────────────────────────────────────────
from qiskit_aer.primitives import EstimatorV2 as AerEstimatorV2
from qiskit_aer.noise import NoiseModel, thermal_relaxation_error, depolarizing_error

# ── Qiskit Algorithms ─────────────────────────────────────────────────────────
from qiskit_algorithms import VQE
from qiskit_algorithms.optimizers import SLSQP

# ── PySCF (classical reference) ───────────────────────────────────────────────
from pyscf import gto, scf, fci as pyscf_fci


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
BASIS         = "sto-3g"
BOND_LENGTHS  = np.arange(0.5, 2.65, 0.15)   # Å  — 15 geometries
BASIS_GATES   = ["u", "cx", "p", "h", "sx", "x"]
ZNE_SCALES    = [1, 3, 5]                      # scale factors for gate folding
SHOTS_NOISY   = 8_192                          # shots for noisy VQE optimisation
SHOTS_ZNE     = 16_384                         # shots per ZNE scale factor point
CHEM_ACC_mEh  = 1.594                          # 1 kcal/mol in milli-Hartree

# Noise parameters (IBM Eagle-like, mild for clear pedagogical demonstration)
T1 = T2       = 200e3   # ns  (200 µs — excellent qubit)
GATE_TIME_1Q  = 50      # ns
GATE_TIME_2Q  = 300     # ns
P_DEPOL_1Q    = 1e-4    # single-qubit depolarizing probability
P_DEPOL_2Q    = 1e-3    # two-qubit (CX) depolarizing probability


# ─────────────────────────────────────────────────────────────────────────────
#  NOISE MODEL
# ─────────────────────────────────────────────────────────────────────────────
def build_noise_model() -> NoiseModel:
    """
    Construct an IBM-like noise model combining:
      • Amplitude damping + dephasing via thermal relaxation (T1, T2)
      • Depolarizing channel for gate-level imperfections

    The two channels are composed (multiplied) so both act simultaneously.
    """
    nm = NoiseModel()

    # --- Single-qubit gate errors ---
    err_1q_thermal = thermal_relaxation_error(T1, T2, GATE_TIME_1Q)
    err_1q_dep     = depolarizing_error(P_DEPOL_1Q, 1)
    err_1q         = err_1q_thermal.compose(err_1q_dep)

    # --- Two-qubit (CX) gate errors (tensor product of per-qubit thermal) ---
    err_2q_thermal = (thermal_relaxation_error(T1, T2, GATE_TIME_2Q)
                      .expand(thermal_relaxation_error(T1, T2, GATE_TIME_2Q)))
    err_2q_dep     = depolarizing_error(P_DEPOL_2Q, 2)
    err_2q         = err_2q_thermal.compose(err_2q_dep)

    nm.add_all_qubit_quantum_error(err_1q, ["u", "p", "h", "sx", "x"])
    nm.add_all_qubit_quantum_error(err_2q, ["cx"])
    return nm


# ─────────────────────────────────────────────────────────────────────────────
#  ZNE — GATE FOLDING
# ─────────────────────────────────────────────────────────────────────────────
def fold_cx_gates(circuit: QuantumCircuit, scale_factor: int) -> QuantumCircuit:
    """
    Two-qubit gate folding for ZNE.

    Replace every CX gate G with  G · (G† · G)^n  where n = (λ−1)/2.
    This increases the effective noise on two-qubit gates by factor λ
    while leaving the circuit unitary (G†G = I, so the extra pairs cancel
    mathematically but inject additional noise physically).

    Only CX gates are folded (not single-qubit gates) to avoid excessive
    circuit inflation — CX gates are the dominant noise source on real hardware.

    Parameters
    ----------
    circuit      : transpiled QuantumCircuit with measured parameters
    scale_factor : odd integer ≥ 1  (λ = 1 → no folding)

    Returns
    -------
    QuantumCircuit with folded CX gates.
    """
    if scale_factor == 1:
        return circuit

    n_folds = (scale_factor - 1) // 2
    folded  = QuantumCircuit(*circuit.qregs, *circuit.cregs)

    for inst in circuit.data:
        folded.append(inst)
        if inst.operation.name == "cx":
            for _ in range(n_folds):
                # G†  (CX is self-inverse, so CX† = CX)
                folded.append(inst.operation.inverse(), inst.qubits, inst.clbits)
                # G again
                folded.append(inst)

    return folded


def zne_extrapolate(scale_factors: list, energies: list) -> float:
    """
    Quadratic Richardson extrapolation to the zero-noise limit.

    Fit E(λ) = a·λ² + b·λ + c  and evaluate at λ = 0 → c.
    Quadratic (degree-2) is preferred over linear when using three scale
    factors, as it captures the curvature of the noise-energy relationship.
    """
    coeffs = np.polyfit(scale_factors, energies, deg=2)
    return float(np.polyval(coeffs, 0))


# ─────────────────────────────────────────────────────────────────────────────
#  MOLECULAR SETUP HELPER
# ─────────────────────────────────────────────────────────────────────────────
mapper = JordanWignerMapper()


def build_problem(d: float):
    """
    Return qubit Hamiltonian, transpiled UCCSD ansatz, and nuclear repulsion
    for H₂ at bond length d (Å).
    """
    atom    = f"H 0 0 0; H 0 0 {d:.4f}"
    driver  = PySCFDriver(atom=atom, basis=BASIS)
    problem = driver.run()

    qubit_op  = mapper.map(problem.second_q_ops()[0])
    hf_state  = HartreeFock(problem.num_spatial_orbitals,
                             problem.num_particles, mapper)
    ansatz    = UCCSD(problem.num_spatial_orbitals, problem.num_particles,
                      mapper, initial_state=hf_state)

    # Transpile to hardware basis gates ONCE per geometry.
    # This converts EvolvedOps → native gates that Aer understands.
    ansatz_t  = transpile(
        ansatz.decompose().decompose().decompose(),
        basis_gates=BASIS_GATES,
        optimization_level=3,
        seed_transpiler=42,
    )

    return qubit_op, ansatz_t, problem.nuclear_repulsion_energy


def fci_energy(d: float) -> float:
    """Classical FCI total energy (exact within STO-3G basis)."""
    atom = f"H 0 0 0; H 0 0 {d:.4f}"
    mol  = gto.M(atom=atom, basis=BASIS, verbose=0)
    mf   = scf.RHF(mol).run()
    return pyscf_fci.FCI(mf).kernel()[0]


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN SCAN
# ─────────────────────────────────────────────────────────────────────────────
noise_model = build_noise_model()

results = {}

print(f"\n{'d (Å)':>6}  {'FCI':>10}  {'Ideal VQE':>10}  {'Noisy VQE':>10}  "
      f"{'ZNE':>10}  {'Δnoisy (mEh)':>13}  {'ΔZNE (mEh)':>11}  Chem.acc?")
print("─" * 90)

for d in BOND_LENGTHS:

    # ── Build problem ─────────────────────────────────────────────────────────
    qubit_op, ansatz_t, nuc_rep = build_problem(d)
    e_fci  = fci_energy(d)

    # ── Phase 1: Ideal VQE (Phase 1 code, reproduced for the combined plot) ──
    res_ideal = VQE(
        StatevectorEstimator(),
        ansatz_t,
        SLSQP(maxiter=150),
    ).compute_minimum_eigenvalue(qubit_op)
    e_ideal = res_ideal.eigenvalue.real + nuc_rep

    # ── Phase 2: Noisy VQE ───────────────────────────────────────────────────
    noisy_est = AerEstimatorV2(options={
        "backend_options": {"noise_model": noise_model},
        "run_options":     {"shots": SHOTS_NOISY},
    })
    res_noisy = VQE(
        noisy_est,
        ansatz_t,
        SLSQP(maxiter=60),
    ).compute_minimum_eigenvalue(qubit_op)

    # Extract the optimal parameters found under noisy conditions
    opt_params = np.array(
        [res_noisy.optimal_parameters[p] for p in ansatz_t.parameters]
    )
    e_noisy = res_noisy.eigenvalue.real + nuc_rep

    # ── Phase 3: ZNE Mitigation ──────────────────────────────────────────────
    # Evaluate the noisy-optimal circuit at each scale factor
    energies_at_scales = []
    for sf in ZNE_SCALES:
        folded_circuit = fold_cx_gates(ansatz_t, sf)

        zne_est = AerEstimatorV2(options={
            "backend_options": {"noise_model": noise_model},
            "run_options":     {"shots": SHOTS_ZNE},
        })
        job = zne_est.run([(folded_circuit, qubit_op, opt_params)])
        e_sf = float(job.result()[0].data.evs) + nuc_rep
        energies_at_scales.append(e_sf)

    e_zne = zne_extrapolate(ZNE_SCALES, energies_at_scales)

    # ── Record results ────────────────────────────────────────────────────────
    err_noisy = abs(e_noisy - e_fci) * 1000   # mEh
    err_zne   = abs(e_zne   - e_fci) * 1000   # mEh
    chem_acc  = "✓" if err_zne < CHEM_ACC_mEh else "✗"

    results[round(d, 4)] = {
        "fci":   e_fci,
        "ideal": e_ideal,
        "noisy": e_noisy,
        "zne":   e_zne,
        "zne_points": {sf: e for sf, e in zip(ZNE_SCALES, energies_at_scales)},
    }

    print(f"{d:6.2f}  {e_fci:10.5f}  {e_ideal:10.5f}  {e_noisy:10.5f}  "
          f"{e_zne:10.5f}  {err_noisy:13.1f}  {err_zne:11.1f}  {chem_acc}")


# ─────────────────────────────────────────────────────────────────────────────
#  SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
all_err_noisy = [abs(r["noisy"] - r["fci"]) * 1000 for r in results.values()]
all_err_zne   = [abs(r["zne"]   - r["fci"]) * 1000 for r in results.values()]

print(f"\n{'─'*55}")
print(f"Average error (noisy VQE): {np.mean(all_err_noisy):7.1f} mEh")
print(f"Average error (ZNE):       {np.mean(all_err_zne):7.1f} mEh")
print(f"Error reduction from ZNE:  {(1 - np.mean(all_err_zne)/np.mean(all_err_noisy))*100:.0f}%")
print(f"ZNE chemical accuracy:     {sum(e < CHEM_ACC_mEh for e in all_err_zne)}/{len(all_err_zne)} geometries")


# ─────────────────────────────────────────────────────────────────────────────
#  PLOT — Three-phase combined figure
# ─────────────────────────────────────────────────────────────────────────────
bond_lengths = list(results.keys())
e_fci_arr   = [results[d]["fci"]   for d in bond_lengths]
e_ideal_arr = [results[d]["ideal"] for d in bond_lengths]
e_noisy_arr = [results[d]["noisy"] for d in bond_lengths]
e_zne_arr   = [results[d]["zne"]   for d in bond_lengths]

fig, axes = plt.subplots(2, 1, figsize=(9, 9),
                          gridspec_kw={"hspace": 0.38})

# ── Panel 1: Dissociation curves ─────────────────────────────────────────────
ax1 = axes[0]

ax1.fill_between(bond_lengths, e_noisy_arr, e_fci_arr,
                 alpha=0.08, color="#d62728", label=None)
ax1.fill_between(bond_lengths, e_zne_arr, e_fci_arr,
                 alpha=0.08, color="#ff7f0e", label=None)

ax1.plot(bond_lengths, e_fci_arr,   "k-",   lw=2.2, label="FCI (exact, classical)")
ax1.plot(bond_lengths, e_ideal_arr, "b--",  lw=1.8, label="Ideal VQE (Phase 1)", dashes=(6,2))
ax1.plot(bond_lengths, e_noisy_arr, "r^-",  lw=1.4, ms=6, label="Noisy VQE (Phase 2, degraded)")
ax1.plot(bond_lengths, e_zne_arr,   "gs-",  lw=1.8, ms=6, label="ZNE mitigated (Phase 3, recovered)")

ax1.axvline(0.74, color="gray", lw=0.9, ls=":", alpha=0.7)
ax1.text(0.74 + 0.03, ax1.get_ylim()[0] + 0.01, "equil.\n0.74 Å",
         fontsize=8, color="gray", va="bottom")

# Chemical accuracy band around FCI
ax1.fill_between(bond_lengths,
                 [e - CHEM_ACC_mEh/1000 for e in e_fci_arr],
                 [e + CHEM_ACC_mEh/1000 for e in e_fci_arr],
                 alpha=0.15, color="black", label="±1 mEh chem. acc. band")

ax1.set_xlabel("H–H bond length (Å)", fontsize=12)
ax1.set_ylabel("Total energy (Hartree)", fontsize=12)
ax1.set_title("H₂ Dissociation Curve — All Three Phases\n"
              "STO-3G basis · Jordan–Wigner mapping · UCCSD ansatz",
              fontsize=12, pad=8)
ax1.legend(fontsize=9, loc="lower right")
ax1.grid(alpha=0.25)

# ── Panel 2: Error comparison ─────────────────────────────────────────────────
ax2 = axes[1]

err_noisy_mEh = [abs(e - f) * 1000 for e, f in zip(e_noisy_arr, e_fci_arr)]
err_zne_mEh   = [abs(e - f) * 1000 for e, f in zip(e_zne_arr,   e_fci_arr)]

ax2.semilogy(bond_lengths, err_noisy_mEh, "r^-", lw=1.5, ms=7,
             label="Noisy VQE error")
ax2.semilogy(bond_lengths, err_zne_mEh,   "gs-", lw=1.8, ms=7,
             label="ZNE mitigated error")
ax2.axhline(CHEM_ACC_mEh, color="black", lw=1.2, ls="--",
            label=f"Chemical accuracy threshold ({CHEM_ACC_mEh} mEh)")

# Shade the recovery region
for xn, xp, en, ez in zip(bond_lengths, bond_lengths, err_noisy_mEh, err_zne_mEh):
    ax2.vlines(xn, ez, en, colors="gray", lw=0.6, alpha=0.4)

ax2.set_xlabel("H–H bond length (Å)", fontsize=12)
ax2.set_ylabel("|E − E_FCI|  (mEh, log scale)", fontsize=12)
ax2.set_title("ZNE Error Recovery vs. Noisy VQE", fontsize=12)
ax2.legend(fontsize=9)
ax2.grid(alpha=0.25, which="both")
ax2.set_ylim(bottom=0.5)

# Annotate average improvement
ax2.text(0.97, 0.92,
         f"Avg error  noisy: {np.mean(err_noisy_mEh):.0f} mEh\n"
         f"Avg error  ZNE:   {np.mean(err_zne_mEh):.1f} mEh\n"
         f"Improvement:  {(1-np.mean(err_zne_mEh)/np.mean(err_noisy_mEh))*100:.0f}%",
         transform=ax2.transAxes, ha="right", va="top", fontsize=9,
         bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                   edgecolor="gray", alpha=0.85))

plt.savefig("h2_three_phase_simulation.png", dpi=150, bbox_inches="tight")
plt.show()
print("\nPlot saved → h2_three_phase_simulation.png")
