# VQE Applied to the Hydrogen Molecule (Dissociation Curve)

## Overview
This repository demonstrates the application of the Variational Quantum Eigensolver (VQE) to calculate the ground state energy of a Hydrogen molecule ($H_2$) across various interatomic distances, ultimately plotting its dissociation curve. 

Because current Quantum Processing Units (QPUs) are prone to decoherence and gate errors, this project is divided into three distinct phases to explore algorithm degradation and subsequent error recovery.

## Project Phases

### Phase 1: Ideal VQE (Mathematically Pure State)
In this phase, we assume a mathematically perfect quantum state utilizing an ideal, noiseless statevector simulator. 
* **Goal:** Establish the baseline dissociation curve.
* **Method:** We use VQE with a standard ansatz (like UCCSD or RealAmplitudes) and a classical optimizer (e.g., COBYLA or SLSQP) to find the minimum eigenvalue of the $H_2$ Hamiltonian at varying atomic distances.

### Phase 2: Algorithm Degradation (Noisy VQE)
Quantum hardware is not perfect. In Phase 2, we inject realistic quantum noise into the simulation.
* **Goal:** Observe how physical quantum noise degrades the VQE algorithm's accuracy.
* **Method:** We apply a noise model (such as depolarizing noise or a simulated backend from IBM Quantum) to the circuit. The resulting ground-state energies deviate significantly from the chemically accurate ideal curve, demonstrating the "barren plateau" and precision loss in noisy intermediate-scale quantum (NISQ) devices.

### Phase 3: Recovery via Zero Noise Extrapolation (ZNE)
To extract useful data from a noisy quantum computer, we must apply Error Mitigation.
* **Goal:** Recover the ideal mathematically pure state from the degraded noisy results.
* **Method:** We employ **Zero Noise Extrapolation (ZNE)**. By intentionally amplifying the noise in our circuits (e.g., via unitary folding) and measuring the expectation values at different noise scale factors, we can mathematically extrapolate the results backwards to the "zero-noise" limit, recovering the ideal dissociation curve.

## Getting Started

### Prerequisites
Ensure you have the following installed:
```bash
pip install qiskit qiskit-aer qiskit-nature matplotlib numpy
