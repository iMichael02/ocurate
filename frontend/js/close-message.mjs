export function closeMessage(code) {
  switch (code) {
    case 1000:
      return "The session has ended.";

    case 4400:
      return "A protocol error occurred. Please start a new session.";

    case 4401:
      return "Your session link is invalid. Please start a new session.";

    case 4408:
      return "The session timed out. Please start a new session.";

    case 4409:
      return "This service version is not supported. Please start a new session.";

    case 1011:
      return "The service could not load the passage. Please start a new session.";

    case 1013:
      return "The service is currently full. Please try again later.";

    default:
      return "Connection to the service was lost.";
  }
}
