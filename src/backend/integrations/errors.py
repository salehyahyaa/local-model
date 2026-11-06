class DuplicateNameError(Exception):
    pass


class McpError(Exception):
    pass


class LoginNotConfirmed(Exception):
    """Its text is shown on the form. The integration isn't saved."""
