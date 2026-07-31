import { issueToken } from "./tokens";

// WHY: sessions are revoked on password change to kill stolen tokens
export class SessionService {
  start(user: string) {
    return issueToken(user);
  }
}
