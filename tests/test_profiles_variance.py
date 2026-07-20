import numpy as np
import pytest
from scipy.stats import beta

from app.simulation.profiles import AgentProfileGenerator


def test_sample_beta_variance_multiplier():
    """Test that variance multiplier increases variance while preserving mean."""
    generator = AgentProfileGenerator()

    # Test parameters
    alpha, beta_param = 2.0, 5.0
    low, high = 0.0, 1.0

    # Get baseline mean and variance
    baseline_mean = alpha / (alpha + beta_param)
    baseline_variance = (alpha * beta_param) / ((alpha + beta_param) ** 2 * (alpha + beta_param + 1))

    # Test with variance multiplier = 1.0 (should be unchanged)
    samples_1 = [generator._sample_beta(alpha, beta_param, low, high, 1.0) for _ in range(10000)]
    mean_1 = np.mean(samples_1)
    var_1 = np.var(samples_1)

    # Test with variance multiplier = 2.0 (should double variance)
    samples_2 = [generator._sample_beta(alpha, beta_param, low, high, 2.0) for _ in range(10000)]
    mean_2 = np.mean(samples_2)
    var_2 = np.var(samples_2)

    # Mean should be preserved (approximately)
    assert abs(mean_1 - baseline_mean) < 0.01
    assert abs(mean_2 - baseline_mean) < 0.01
    assert abs(mean_1 - mean_2) < 0.01  # Means should be similar

    # Variance should increase with multiplier
    # Note: due to clipping and sampling, we expect approximate doubling
    assert var_2 > var_1
    # Check that variance roughly doubled (allowing for sampling error and clipping effects)
    assert var_2 / var_1 > 1.5  # At least 50% increase


def test_sample_beta_variance_multiplier_clipping():
    """Test that variance multiplier works with clipping bounds."""
    generator = AgentProfileGenerator()

    # Parameters that would produce values outside [0.03, 0.97] without clipping
    alpha, beta_param = 0.5, 0.5  # U-shaped distribution
    low, high = 0.03, 0.97

    # Test with high variance multiplier
    samples = [generator._sample_beta(alpha, beta_param, low, high, 3.0) for _ in range(1000)]

    # All samples should be within bounds
    assert all(low <= s <= high for s in samples)

    # Should still get variation
    assert np.var(samples) > 0.001


def test_generate_one_applies_variance_multiplier(monkeypatch):
    """Test that AgentProfileGenerator.generate_one uses the config variance multiplier."""
    import backend.app.simulation.profiles as profiles_module
    monkeypatch.setattr(profiles_module.settings, "CLUSTER_VARIANCE_MULTIPLIER", 1.5)

    generator = AgentProfileGenerator()

    # We'll monkey patch _sample_beta to capture the variance_multiplier argument
    original_sample_beta = generator._sample_beta
    captured_multiplier = []

    def mock_sample_beta(alpha, beta_param, low=0.03, high=0.97, variance_multiplier=1.0):
        captured_multiplier.append(variance_multiplier)
        return original_sample_beta(alpha, beta_param, low, high, variance_multiplier)

    generator._sample_beta = mock_sample_beta

    # Generate a profile (we need to provide minimal env_params)
    env_params = {}  # Not used in current implementation
    profile = generator.generate_one(env_params, scenario_type=None)

    # Check that variance_multiplier was passed as 1.5
    assert len(captured_multiplier) == 5  # One for each trait
    assert all(m == 1.5 for m in captured_multiplier)

    # Verify we got a valid profile
    assert hasattr(profile, 'digital_literacy')
    assert 0.03 <= profile.digital_literacy <= 0.97