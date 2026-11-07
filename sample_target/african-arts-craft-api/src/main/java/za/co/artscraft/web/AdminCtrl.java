package za.co.artscraft.web;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

@RestController
public class AdminCtrl {

    @DeleteMapping("/admin/users/{id}")
    public void deleteUser(@PathVariable long id) {
        // deletes a customer account
    }

    @PreAuthorize("hasRole('ADMIN')")
    @GetMapping("/admin/reports")
    public String reports() {
        return "ok";
    }
}
