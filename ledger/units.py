from fractions import Fraction


def require_name(value, label):
    if not isinstance(value, str) or not value or value != value.strip() or '\0' in value:
        raise ValueError(f'{label} must be a nonempty, trimmed string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError(f'invalid {label}') from error
    return value


def parse_rational(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('expected an integer, rational string or Fraction')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f'invalid rational value: {value!r}') from error


def validate_trial_unit(unit):
    return require_name(unit, 'trial unit')


def require_matching_unit(expected, actual):
    if validate_trial_unit(actual) != expected:
        raise ValueError(f'expected the trial unit {expected!r}, received {actual!r}')
