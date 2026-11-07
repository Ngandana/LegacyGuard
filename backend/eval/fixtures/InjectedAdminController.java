package za.ac.cput.eval;

import jakarta.annotation.security.RolesAllowed;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/injected")   // GT:CWE-862
public class InjectedAdminController {

    @DeleteMapping("/admin/users/{id}")   // GT:CWE-862
    public void deleteUser(@PathVariable long id) { }

    @PostMapping("/admin/reset")   // GT:CWE-862
    public void reset() { }

    @GetMapping("/admin/export")   // GT:CWE-862
    public String export() { return "x"; }

    @RolesAllowed("ADMIN")
    @GetMapping("/admin/reports")   // TN (authorised)
    public String reports() { return "ok"; }

    @GetMapping("/public/health")   // TN (not a sensitive path)
    public String health() { return "up"; }
}
